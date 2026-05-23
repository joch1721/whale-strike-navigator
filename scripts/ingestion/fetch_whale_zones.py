"""
fetch_whale_zones.py
--------------------
Downloads NOAA North Atlantic Right Whale Seasonal Management Area (SMA)
polygons from the NOAA ArcGIS REST API and saves them as GeoJSON and Parquet.

These zones define where vessels ≥65ft must slow to ≤10 knots during specific
months. They are the regulatory ground-truth for the whale presence layer in
the risk score engine.

Usage (run from backend/):
    python ../scripts/ingestion/fetch_whale_zones.py

Outputs:
    data/shapefiles/narw_sma_zones.geojson   — raw GeoJSON for Mapbox
    data/shapefiles/narw_sma_zones.parquet   — cleaned tabular form for risk engine

Source:
    NOAA ArcGIS REST API (no login required)
    https://coast.noaa.gov/arcgismc/rest/services/OceanReports/OceanReports/MapServer/41
"""

import json
import sys
from pathlib import Path

import httpx
import geopandas as gpd
import pandas as pd
from shapely.geometry import shape
from loguru import logger

# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# ── Config ────────────────────────────────────────────────────────────────────

# NOAA ArcGIS REST endpoint for NARW Seasonal Management Areas
# Returns up to 2000 features as GeoJSON
ARCGIS_URL = (
    "https://coast.noaa.gov/arcgismc/rest/services/"
    "OceanReports/OceanReports/MapServer/41/query"
)

# Fallback: GARFO direct shapefile download (zipped)
GARFO_URL = (
    "https://www.greateratlantic.fisheries.noaa.gov/"
    "educational_resources/gis/data/inuse/protected_species/"
    "right_whale/RightWhale_SMA.zip"
)

# Output directory
OUT_DIR = REPO_ROOT / "data" / "shapefiles"

# ── Known SMA active months ───────────────────────────────────────────────────
# These are the regulatory active periods per zone name.
# Source: 50 CFR Part 224.105
# We embed this here because the shapefile attributes don't always include
# month data — they're spatial-only.
SMA_MONTH_MAP = {
    "Southeast U.S.":               [11, 12, 1, 2, 3, 4],   # Nov–Apr
    "Cape Cod Bay":                  [1, 2, 3, 4, 5],         # Jan–May
    "Great South Channel":           [4, 5, 6, 7],            # Apr–Jul
    "Off Race Point":                [3, 4, 5, 6, 7, 8],      # Mar–Aug (seasonal)
    "New York/New Jersey Port":      [11, 12, 1, 2, 3, 4],   # Nov–Apr
    "Block Island Sound":            [11, 12, 1, 2, 3, 4],   # Nov–Apr
    "Mid-Atlantic":                  [11, 12, 1, 2, 3, 4],   # Nov–Apr
}

# Fallback months if zone name doesn't match — conservative (all winter months)
DEFAULT_MONTHS = [11, 12, 1, 2, 3, 4]


# ── ArcGIS REST fetch ─────────────────────────────────────────────────────────

def fetch_arcgis() -> dict | None:
    """
    Query the NOAA ArcGIS REST service for all SMA polygons.
    Returns a GeoJSON FeatureCollection dict, or None on failure.
    """
    params = {
        "where": "1=1",           # all features
        "outFields": "*",         # all attributes
        "f": "geojson",           # GeoJSON output
        "outSR": "4326",          # WGS84
        "returnGeometry": "true",
    }

    logger.info("Fetching SMA zones from NOAA ArcGIS REST API...")
    try:
        r = httpx.get(ARCGIS_URL, params=params, timeout=60, follow_redirects=True)
        r.raise_for_status()
        data = r.json()

        features = data.get("features", [])
        if not features:
            logger.warning("ArcGIS returned 0 features")
            return None

        logger.success(f"  Got {len(features)} SMA zones from ArcGIS")
        return data

    except Exception as e:
        logger.warning(f"ArcGIS fetch failed: {e}")
        return None


# ── Cleaning ──────────────────────────────────────────────────────────────────

def extract_zone_name(props: dict) -> str:
    """Try several common attribute names for zone name."""
    for key in ["INFORM", "NAME", "Zone_Name", "ZONE_NAME", "SMA_NAME", "name"]:
        val = props.get(key)
        if val and str(val).strip():
            return str(val).strip()
    return "Unknown SMA Zone"


def assign_months(zone_name: str) -> list[int]:
    """Match zone name to known active months."""
    for key, months in SMA_MONTH_MAP.items():
        if key.lower() in zone_name.lower():
            return months
    return DEFAULT_MONTHS


def clean_geojson(raw: dict) -> dict:
    """
    Enrich each feature with:
    - zone_name (normalised)
    - active_months (list of ints)
    - speed_limit_knots (always 10 for SMAs)
    - regulatory (True — these are enforceable zones)
    """
    cleaned_features = []
    for feat in raw.get("features", []):
        props = feat.get("properties", {}) or {}
        geom  = feat.get("geometry")

        if not geom:
            continue

        zone_name = extract_zone_name(props)
        active_months = assign_months(zone_name)

        cleaned_features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "zone_name":         zone_name,
                "species_code":      "NARW",
                "active_months":     active_months,
                "speed_limit_knots": 10.0,
                "regulatory":        True,
                "source":            "NOAA ArcGIS REST / 50 CFR 224.105",
                # Preserve original attributes for reference
                **{f"orig_{k}": v for k, v in props.items()},
            },
        })

    return {"type": "FeatureCollection", "features": cleaned_features}


# ── Build tabular form for risk engine ───────────────────────────────────────

def geojson_to_parquet(geojson: dict, out_path: Path) -> None:
    """
    Convert GeoJSON FeatureCollection to a GeoDataFrame and save as Parquet.
    The risk engine uses this to test point-in-polygon for each grid cell.
    """
    features = geojson.get("features", [])
    if not features:
        logger.warning("No features to convert to Parquet")
        return

    rows = []
    geometries = []
    for feat in features:
        props = {k: v for k, v in feat["properties"].items()
                 if not k.startswith("orig_")}
        # Store active_months as comma-separated string (Parquet doesn't support lists natively)
        props["active_months_str"] = ",".join(str(m) for m in props.get("active_months", []))
        props.pop("active_months", None)
        rows.append(props)
        geometries.append(shape(feat["geometry"]))

    gdf = gpd.GeoDataFrame(rows, geometry=geometries, crs="EPSG:4326")
    gdf.to_parquet(out_path)
    logger.success(f"  Saved GeoDataFrame → {out_path.name} ({len(gdf)} zones)")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    geojson_path  = OUT_DIR / "narw_sma_zones.geojson"
    parquet_path  = OUT_DIR / "narw_sma_zones.parquet"

    if geojson_path.exists() and parquet_path.exists():
        logger.info("SMA zones already downloaded — skipping")
        logger.info(f"  {geojson_path}")
        logger.info(f"  {parquet_path}")
        return

    # ── Fetch ─────────────────────────────────────────────────────────────────
    raw = fetch_arcgis()

    if raw is None:
        logger.error("ArcGIS fetch failed. Check your internet connection and try again.")
        logger.info(f"Manual fallback: download the shapefile from:\n  {GARFO_URL}")
        sys.exit(1)

    # ── Clean ─────────────────────────────────────────────────────────────────
    cleaned = clean_geojson(raw)
    logger.info(f"Cleaned {len(cleaned['features'])} zones")

    for feat in cleaned["features"]:
        p = feat["properties"]
        logger.info(f"  {p['zone_name']} — active months: {p['active_months']}")

    # ── Save GeoJSON (for Mapbox) ─────────────────────────────────────────────
    with open(geojson_path, "w") as f:
        json.dump(cleaned, f, indent=2)
    logger.success(f"Saved GeoJSON → {geojson_path.name}")

    # ── Save Parquet (for risk engine) ────────────────────────────────────────
    geojson_to_parquet(cleaned, parquet_path)

    logger.success("Step 1.4 complete — NARW SMA zones ready.")
    logger.info(f"  GeoJSON: {geojson_path}")
    logger.info(f"  Parquet: {parquet_path}")


if __name__ == "__main__":
    main()
