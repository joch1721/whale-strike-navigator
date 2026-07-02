"""
build_whale_presence.py
-----------------------
Step 2.3 — Whale presence probability layer.

For each ocean grid cell and each month, computes a whale presence
probability (0–1) by combining two sources:

  1. KDE score — kernel density estimate from OBIS/GBIF occurrence records,
     normalized per species per month to 0–1.

  2. Zone overlap — binary 1.0 if the cell centre falls inside an active
     NOAA Seasonal Management Area (SMA) for that month.

Combined as: whale_presence_prob = max(KDE_score, zone_overlap)

This matches the methodology in docs/methodology.md.

Usage (run from backend/):
    python ../scripts/processing/build_whale_presence.py

Outputs:
    data/processed/whale_presence_<MM>.parquet  (one per month)

Schema:
    cell_id              str     join key to grid_cells.parquet
    lat                  float   cell centre latitude
    lon                  float   cell centre longitude
    month                int     1–12
    kde_score            float   0–1 normalized occurrence density
    zone_overlap         float   0 or 1 — inside active SMA zone
    whale_presence_prob  float   max(kde_score, zone_overlap)
    species_present      str     comma-separated species contributing to score
"""

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde
from shapely.geometry import Point
from loguru import logger

# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# ── Paths ─────────────────────────────────────────────────────────────────────
WHALE_DIR  = REPO_ROOT / "data" / "raw" / "whale_occurrences"
ZONES_PATH = REPO_ROOT / "data" / "shapefiles" / "narw_sma_zones.parquet"
GRID_PATH  = REPO_ROOT / "data" / "processed" / "grid_cells.parquet"
OUT_DIR    = REPO_ROOT / "data" / "processed"

# ── Constants ─────────────────────────────────────────────────────────────────

# KDE bandwidth in degrees (0.5° ≈ 55 km — smooths over data-sparse areas)
KDE_BANDWIDTH = 0.5

# Minimum occurrences needed to fit a KDE for a species/month
MIN_OCCURRENCES = 5

# All 12 months
ALL_MONTHS = list(range(1, 13))


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_occurrences() -> pd.DataFrame:
    frames = []
    for f in sorted(WHALE_DIR.glob("*_occurrences.parquet")):
        df = pd.read_parquet(f)
        frames.append(df)
    if not frames:
        logger.error("No whale occurrence files found")
        sys.exit(1)
    combined = pd.concat(frames, ignore_index=True)
    combined["month"] = pd.to_numeric(combined["month"], errors="coerce")
    combined = combined.dropna(subset=["lat", "lon", "month", "species_code"])
    logger.info(f"Loaded {len(combined):,} whale occurrence records")
    return combined


def load_zones() -> gpd.GeoDataFrame:
    gdf = gpd.read_parquet(ZONES_PATH)
    gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    # Parse active_months_str back to list of ints
    gdf["active_months"] = gdf["active_months_str"].apply(
        lambda s: [int(m) for m in s.split(",") if m.strip()]
    )
    logger.info(f"Loaded {len(gdf)} SMA zones")
    return gdf


def load_grid() -> pd.DataFrame:
    grid = pd.read_parquet(GRID_PATH)
    logger.info(f"Loaded {len(grid):,} ocean grid cells")
    return grid


# ── KDE ───────────────────────────────────────────────────────────────────────

def compute_kde_scores(
    occurrences: pd.DataFrame,
    grid: pd.DataFrame,
    month: int,
) -> pd.DataFrame:
    """
    For each species with enough records in this month, fit a Gaussian KDE
    and evaluate at every grid cell centre. Normalize scores to 0–1.
    Returns a DataFrame with columns: cell_id, kde_score, species_present.
    """
    month_occ = occurrences[occurrences["month"] == month]

    # Start with zeros for all cells
    result = grid[["cell_id", "lat", "lon"]].copy()
    result["kde_score"] = 0.0
    result["species_present"] = ""

    cell_lons = result["lon"].values
    cell_lats = result["lat"].values
    eval_points = np.vstack([cell_lons, cell_lats])  # (2, N)

    for species, grp in month_occ.groupby("species_code"):
        if len(grp) < MIN_OCCURRENCES:
            logger.debug(f"    {species} month {month}: only {len(grp)} records — skipping KDE")
            continue

        try:
            kde = gaussian_kde(
                np.vstack([grp["lon"].values, grp["lat"].values]),
                bw_method=KDE_BANDWIDTH,
            )
            scores = kde(eval_points)

            # Normalize to 0–1 using 95th percentile as ceiling — prevents a single
            # outlier cluster (e.g. Gulf of St. Lawrence survey effort, which has
            # no AIS coverage) from suppressing signal everywhere else
            p95 = np.percentile(scores, 95)
            if p95 > 0:
                scores = np.clip(scores / p95, 0, 1)
            else:
                scores = np.zeros_like(scores)

            # Take max across species (a cell is high-risk if ANY species is present)
            result["kde_score"] = np.maximum(result["kde_score"].values, scores)

            # Track which species contributed
            mask = scores > 0.01  # threshold to avoid noise
            result.loc[mask, "species_present"] = result.loc[mask, "species_present"].apply(
                lambda s: (s + "," + species).strip(",") if species not in s else s
            )

            logger.debug(f"    {species}: KDE fitted on {len(grp)} records, "
                        f"max score={scores.max():.3f}")

        except Exception as e:
            logger.warning(f"    KDE failed for {species} month {month}: {e}")

    n_active = (result["kde_score"] > 0.01).sum()
    logger.info(f"  KDE: {n_active:,} cells with whale presence signal")
    return result


# ── Zone overlap ──────────────────────────────────────────────────────────────

def compute_zone_overlap(
    grid: pd.DataFrame,
    zones: gpd.GeoDataFrame,
    month: int,
) -> pd.Series:
    """
    For each grid cell centre, check if it falls inside any SMA zone
    that is active during this month. Returns a Series indexed like grid.
    """
    # Filter zones active this month
    active_zones = zones[zones["active_months"].apply(lambda ms: month in ms)]

    if active_zones.empty:
        logger.info(f"  Zone overlap: no active SMA zones for month {month}")
        return pd.Series(0.0, index=grid.index)

    logger.info(f"  Zone overlap: {len(active_zones)} active zones for month {month}")

    # Build GeoDataFrame of grid cell centres
    grid_gdf = gpd.GeoDataFrame(
        grid[["cell_id"]].copy(),
        geometry=gpd.points_from_xy(grid["lon"], grid["lat"]),
        crs="EPSG:4326",
    )

    # Spatial join — cells inside any active zone get overlap = 1.0
    joined = gpd.sjoin(grid_gdf, active_zones[["geometry"]], how="left", predicate="within")
    in_zone = joined["index_right"].notna()

    # Handle duplicate rows from sjoin (cell in multiple zones)
    in_zone = in_zone.groupby(level=0).any()

    overlap = in_zone.astype(float)
    n_in_zone = int(overlap.sum())
    logger.info(f"  Zone overlap: {n_in_zone:,} cells inside active SMA zones")

    return overlap


# ── Main per-month computation ────────────────────────────────────────────────

def compute_month(
    month: int,
    occurrences: pd.DataFrame,
    grid: pd.DataFrame,
    zones: gpd.GeoDataFrame,
) -> pd.DataFrame:
    logger.info(f"── Month {month:02d} ──")

    # KDE scores
    kde_df = compute_kde_scores(occurrences, grid, month)

    # Zone overlap
    zone_series = compute_zone_overlap(grid, zones, month)
    kde_df["zone_overlap"] = zone_series.values

    # Combined: max(KDE, zone)
    kde_df["whale_presence_prob"] = np.maximum(
        kde_df["kde_score"].values,
        kde_df["zone_overlap"].values,
    ).round(4)

    kde_df["kde_score"]    = kde_df["kde_score"].round(4)
    kde_df["zone_overlap"] = kde_df["zone_overlap"].round(4)
    kde_df["month"]        = month

    n_nonzero = (kde_df["whale_presence_prob"] > 0).sum()
    logger.info(
        f"  whale_presence_prob: {n_nonzero:,} cells > 0  |  "
        f"max={kde_df['whale_presence_prob'].max():.3f}  |  "
        f"mean={kde_df['whale_presence_prob'].mean():.4f}"
    )

    return kde_df[[
        "cell_id", "lat", "lon", "month",
        "kde_score", "zone_overlap",
        "whale_presence_prob", "species_present",
    ]]


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    occurrences = load_occurrences()
    grid        = load_grid()
    zones       = load_zones()

    for month in ALL_MONTHS:
        out_path = OUT_DIR / f"whale_presence_{month:02d}.parquet"
        if out_path.exists():
            logger.info(f"Month {month:02d} already computed — skipping")
            continue

        df = compute_month(month, occurrences, grid, zones)
        df.to_parquet(out_path, index=False)

        size_mb = out_path.stat().st_size / 1_000_000
        logger.success(f"  Saved → {out_path.name} ({size_mb:.1f} MB)")

    logger.success("Step 2.3 complete — whale presence layers ready.")
    logger.info("Output files:")
    for f in sorted(OUT_DIR.glob("whale_presence_*.parquet")):
        df = pd.read_parquet(f)
        n_active = (df["whale_presence_prob"] > 0).sum()
        logger.info(
            f"  {f.name}: {n_active:,} active cells / {len(df):,} total  |  "
            f"max prob={df['whale_presence_prob'].max():.3f}"
        )


if __name__ == "__main__":
    main()
