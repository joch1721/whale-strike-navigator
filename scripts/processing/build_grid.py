"""
build_grid.py
-------------
Step 2.1 — Grid cell definition.

Generates the 0.1° × 0.1° ocean grid that underpins the entire risk score
engine. Each cell is identified by its centre coordinate and assigned a
unique ID used as the join key across all downstream datasets.

Land cells are excluded using a low-resolution Natural Earth land mask
downloaded directly from the GeoPandas built-in datasets — no external
download required.

Usage (run from backend/):
    python ../scripts/processing/build_grid.py

Outputs:
    data/processed/grid_cells.parquet   — full ocean grid, one row per cell

Cell schema:
    cell_id     str     "lat_lon" at cell centre e.g. "42.05_-70.15"
    lat         float   cell centre latitude
    lon         float   cell centre longitude
    lat_min     float   southern edge
    lat_max     float   northern edge
    lon_min     float   western edge
    lon_max     float   eastern edge
    is_ocean    bool    True = ocean cell (land cells excluded from output)
"""

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box, Point
from loguru import logger

# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# ── Config ────────────────────────────────────────────────────────────────────

# Grid resolution in degrees
RESOLUTION = 0.1

# Bounding boxes to generate grid for (min_lon, min_lat, max_lon, max_lat)
# We generate one unified grid covering all NARW habitat zones
GRID_BOUNDS = {
    "atlantic": (-82.0, 24.0, -60.0, 50.0),   # Gulf of Maine + Gulf of St. Lawrence + SE US
    "pacific":  (-124.0, 32.0, -117.0, 38.5), # Santa Barbara + Gulf of Farallones
}

# Output
OUT_DIR  = REPO_ROOT / "data" / "processed"
OUT_PATH = OUT_DIR / "grid_cells.parquet"


# ── Land mask ─────────────────────────────────────────────────────────────────

def load_land_mask() -> gpd.GeoDataFrame:
    """
    Load a low-resolution land polygon dataset to filter out land cells.
    Downloads via httpx with certifi SSL to avoid Mac certificate issues.
    """
    import io, ssl, certifi, httpx, json

    logger.info("Loading land mask (Natural Earth 110m)...")
    url = (
        "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
        "master/geojson/ne_110m_land.geojson"
    )
    try:
        r = httpx.get(url, timeout=30, verify=certifi.where())
        r.raise_for_status()
        land = gpd.read_file(io.BytesIO(r.content))
        logger.success(f"  Downloaded {len(land)} land polygons")
        return land
    except Exception as e:
        logger.warning(f"  Download failed: {e}")
        logger.info("  Using minimal bounding-box land mask as fallback...")
        # Minimal fallback: just a rough land polygon for the continental US
        from shapely.geometry import box
        land_boxes = [
            box(-125, 24, -66, 50),   # continental US
            box(-141, 49, -52, 84),   # Canada
            box(-82, 8, -59, 12),     # Caribbean
        ]
        land = gpd.GeoDataFrame(geometry=land_boxes, crs="EPSG:4326")
        logger.warning("  Using rough fallback land mask — some coastal cells may be wrong")
        return land


# ── Grid generation ───────────────────────────────────────────────────────────

def generate_grid_cells(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    resolution: float = RESOLUTION,
) -> pd.DataFrame:
    """
    Generate all grid cell centre points and edges for a bounding box.
    Returns a DataFrame — geometry column added later for spatial ops.
    """
    # Cell centres: offset by half a resolution from the edge
    half = resolution / 2

    lats = np.arange(min_lat + half, max_lat, resolution)
    lons = np.arange(min_lon + half, max_lon, resolution)

    logger.info(f"  Grid: {len(lats)} lat steps × {len(lons)} lon steps = {len(lats)*len(lons):,} cells")

    rows = []
    for lat in lats:
        for lon in lons:
            rows.append({
                "lat":     round(float(lat), 6),
                "lon":     round(float(lon), 6),
                "lat_min": round(float(lat - half), 6),
                "lat_max": round(float(lat + half), 6),
                "lon_min": round(float(lon - half), 6),
                "lon_max": round(float(lon + half), 6),
            })

    df = pd.DataFrame(rows)

    # Unique cell ID — used as join key everywhere downstream
    df["cell_id"] = (
        df["lat"].round(2).astype(str) + "_" +
        df["lon"].round(2).astype(str)
    )

    return df


# ── Ocean filter ──────────────────────────────────────────────────────────────

def filter_ocean_cells(df: pd.DataFrame, land: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Remove cells whose centre point falls on land.
    Uses a spatial join between cell centres and land polygons.
    """
    logger.info("Filtering land cells...")

    # Build GeoDataFrame of cell centre points
    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["lon"], df["lat"]),
        crs="EPSG:4326",
    )

    # Spatial join — any cell whose centre intersects land is a land cell
    joined = gpd.sjoin(gdf, land[["geometry"]], how="left", predicate="within")
    ocean_mask = joined["index_right"].isna()

    n_total  = len(df)
    n_ocean  = int(ocean_mask.sum())
    n_land   = n_total - n_ocean

    logger.info(f"  Total cells:  {n_total:,}")
    logger.info(f"  Ocean cells:  {n_ocean:,}")
    logger.info(f"  Land cells:   {n_land:,} (excluded)")

    return df[ocean_mask.values].reset_index(drop=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if OUT_PATH.exists():
        df = pd.read_parquet(OUT_PATH)
        logger.info(f"Grid already built — {len(df):,} ocean cells in {OUT_PATH.name}")
        logger.info("Delete the file and re-run to rebuild.")
        return

    land = load_land_mask()

    all_frames = []
    for region, (min_lon, min_lat, max_lon, max_lat) in GRID_BOUNDS.items():
        logger.info(f"Generating grid for {region} ({min_lon},{min_lat}) → ({max_lon},{max_lat})")
        df = generate_grid_cells(min_lon, min_lat, max_lon, max_lat)
        df = filter_ocean_cells(df, land)
        df["region"] = region
        all_frames.append(df)

    grid = pd.concat(all_frames, ignore_index=True)

    # Final column order
    grid = grid[[
        "cell_id", "lat", "lon",
        "lat_min", "lat_max",
        "lon_min", "lon_max",
        "region",
    ]]

    grid.to_parquet(OUT_PATH, index=False)
    size_mb = OUT_PATH.stat().st_size / 1_000_000

    logger.success(f"Grid saved → {OUT_PATH.name}")
    logger.info(f"  {len(grid):,} ocean cells ({size_mb:.1f} MB)")
    logger.info(f"  Lat range: {grid['lat'].min():.2f} – {grid['lat'].max():.2f}")
    logger.info(f"  Lon range: {grid['lon'].min():.2f} – {grid['lon'].max():.2f}")
    logger.info(f"  Cell resolution: {RESOLUTION}°")
    logger.info(f"  Sample cell IDs: {grid['cell_id'].head(3).tolist()}")
    logger.success("Step 2.1 complete.")


if __name__ == "__main__":
    main()