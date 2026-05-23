"""
data_loader.py
--------------
Loads all processed Parquet files into memory at startup and exposes
typed accessors used by the API routers.

All data is loaded once at startup and cached in module-level variables.
This keeps endpoint latency low — no disk I/O per request.

Call load_all_data() from the FastAPI lifespan handler.
"""

from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
from loguru import logger

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT      = Path(__file__).resolve().parents[3]
PROCESSED_DIR  = REPO_ROOT / "data" / "processed"
RAW_DIR        = REPO_ROOT / "data" / "raw"
SHAPEFILES_DIR = REPO_ROOT / "data" / "shapefiles"

# ── In-memory cache ───────────────────────────────────────────────────────────
_risk_grid:    Optional[pd.DataFrame]    = None
_incidents:    Optional[pd.DataFrame]    = None
_whale_zones:  Optional[gpd.GeoDataFrame] = None
_occurrences:  Optional[pd.DataFrame]    = None
_grid_cells:   Optional[pd.DataFrame]    = None


# ── Loader ────────────────────────────────────────────────────────────────────

def load_all_data() -> None:
    """
    Load all processed datasets into memory.
    Called once at FastAPI startup via lifespan handler.
    """
    global _risk_grid, _incidents, _whale_zones, _occurrences, _grid_cells

    logger.info("Loading data into memory...")

    # Risk grid (all months combined)
    risk_path = PROCESSED_DIR / "risk_grid_all.parquet"
    if risk_path.exists():
        _risk_grid = pd.read_parquet(risk_path)
        logger.success(f"  Risk grid: {len(_risk_grid):,} rows")
    else:
        logger.warning("  Risk grid not found — run build_risk_scores.py first")

    # Strike incidents (curated only)
    incidents_path = RAW_DIR / "incidents" / "strike_incidents.parquet"
    if incidents_path.exists():
        df = pd.read_parquet(incidents_path)
        _incidents = df[~df["source"].str.contains("OBIS", na=False)]
        logger.success(f"  Incidents: {len(_incidents):,} curated strikes")
    else:
        logger.warning("  Incidents not found — run fetch_strike_incidents.py first")

    # NARW SMA zones
    zones_path = SHAPEFILES_DIR / "narw_sma_zones.parquet"
    if zones_path.exists():
        _whale_zones = gpd.read_parquet(zones_path)
        _whale_zones = _whale_zones.set_crs("EPSG:4326", allow_override=True)
        _whale_zones["active_months"] = _whale_zones["active_months_str"].apply(
            lambda s: [int(m) for m in s.split(",") if m.strip()]
        )
        logger.success(f"  Whale zones: {len(_whale_zones)} SMA zones")
    else:
        logger.warning("  Whale zones not found — run fetch_whale_zones.py first")

    # Whale occurrences (all species combined)
    occ_frames = []
    for f in sorted((RAW_DIR / "whale_occurrences").glob("*_occurrences.parquet")):
        occ_frames.append(pd.read_parquet(f))
    if occ_frames:
        _occurrences = pd.concat(occ_frames, ignore_index=True)
        logger.success(f"  Occurrences: {len(_occurrences):,} records")
    else:
        logger.warning("  No occurrence files found")

    # Grid cells
    grid_path = PROCESSED_DIR / "grid_cells.parquet"
    if grid_path.exists():
        _grid_cells = pd.read_parquet(grid_path)
        logger.success(f"  Grid cells: {len(_grid_cells):,} ocean cells")
    else:
        logger.warning("  Grid cells not found — run build_grid.py first")

    logger.success("Data loading complete.")


# ── Accessors ─────────────────────────────────────────────────────────────────

def get_risk_grid(
    month: Optional[int] = None,
    species: Optional[str] = None,
    min_score: float = 0.0,
) -> pd.DataFrame:
    """
    Return risk grid rows filtered by month, species, and minimum score.
    """
    if _risk_grid is None:
        return pd.DataFrame()

    df = _risk_grid.copy()

    if month is not None:
        df = df[df["month"] == month]

    if species is not None:
        species_upper = species.upper()
        df = df[df["species_present"].str.contains(species_upper, na=False)]

    if min_score > 0:
        df = df[df["risk_score"] >= min_score]

    return df


def get_incidents(
    species: Optional[str] = None,
    month: Optional[int] = None,
    min_year: Optional[int] = None,
) -> pd.DataFrame:
    if _incidents is None:
        return pd.DataFrame()

    df = _incidents.copy()

    if species:
        df = df[df["species_code"] == species.upper()]
    if month:
        df = df[df["month"] == month]
    if min_year:
        df = df[df["year"] >= min_year]

    return df


def get_whale_zones(month: Optional[int] = None) -> gpd.GeoDataFrame:
    if _whale_zones is None:
        return gpd.GeoDataFrame()

    if month is None:
        return _whale_zones

    return _whale_zones[
        _whale_zones["active_months"].apply(lambda ms: month in ms)
    ]


def get_occurrences(
    species: Optional[str] = None,
    month: Optional[int] = None,
) -> pd.DataFrame:
    if _occurrences is None:
        return pd.DataFrame()

    df = _occurrences.copy()

    if species:
        df = df[df["species_code"] == species.upper()]
    if month:
        df = df[df["month"] == month]

    return df


def is_data_loaded() -> bool:
    return _risk_grid is not None
