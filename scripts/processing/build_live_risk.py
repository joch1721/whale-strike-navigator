"""
build_live_risk.py
------------------
Processes today's live aisstream.io Parquet file into a real-time risk grid
that overlays the historical monthly grid with current vessel positions.

This runs on a schedule (every 15 minutes via APScheduler) and produces:
    data/processed/risk_grid_live.parquet

The live grid uses the same formula as the historical grid but:
  - Uses only today's collected vessel positions (not monthly AIS samples)
  - Inherits whale presence probability from the current calendar month
  - Produces a "live overlay" rather than replacing the historical grid

The frontend can blend both: historical for seasonal context,
live for current vessel positions.

Usage (run from backend/):
    python ../scripts/processing/build_live_risk.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from loguru import logger

# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# ── Paths ─────────────────────────────────────────────────────────────────────
AIS_DIR       = REPO_ROOT / "data" / "raw" / "ais"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
OUT_PATH      = PROCESSED_DIR / "risk_grid_live.parquet"

MAX_REALISTIC_SPEED = 40.0

# ── Vessel type weights (same as build_shipping_density.py) ───────────────────
VESSEL_TYPE_WEIGHTS: dict[int, float] = {
    80: 1.0, 81: 1.0, 82: 1.0, 83: 1.0, 84: 1.0,
    85: 1.0, 86: 1.0, 87: 1.0, 88: 1.0, 89: 1.0,
    70: 1.0, 71: 1.0, 72: 1.0, 73: 1.0, 74: 1.0,
    75: 1.0, 76: 1.0, 77: 1.0, 78: 1.0, 79: 1.0,
    60: 0.9, 61: 0.9, 62: 0.9, 63: 0.9, 64: 0.9,
    65: 0.9, 66: 0.9, 67: 0.9, 68: 0.9, 69: 0.9,
    40: 0.95, 41: 0.95, 42: 0.95, 43: 0.95, 44: 0.95,
    30: 0.4, 31: 0.4, 32: 0.4, 33: 0.4, 34: 0.4,
    35: 0.4, 36: 0.1, 37: 0.1,
    52: 0.3, 53: 0.3,
    0: 0.5,
}


def get_vessel_weight(type_code) -> float:
    try:
        code = int(type_code)
    except (ValueError, TypeError):
        return 0.5
    if code in VESSEL_TYPE_WEIGHTS:
        return VESSEL_TYPE_WEIGHTS[code]
    return VESSEL_TYPE_WEIGHTS.get((code // 10) * 10, 0.5)


def speed_factor(knots: float) -> float:
    if knots <= 10:   return 0.3
    elif knots <= 14: return 0.6
    else:             return 1.0


def snap_to_grid(df: pd.DataFrame, resolution: float = 0.1) -> pd.DataFrame:
    half = resolution / 2
    df["cell_lat"] = (np.floor(df["lat"] / resolution) * resolution + half).round(6)
    df["cell_lon"] = (np.floor(df["lon"] / resolution) * resolution + half).round(6)
    df["cell_id"]  = df["cell_lat"].round(2).astype(str) + "_" + df["cell_lon"].round(2).astype(str)
    return df


def normalize_live_density(series: pd.Series) -> pd.Series:
    REFERENCE_MAX = 50  # vessels per cell — calibrated to live feed density
    log_vals = np.log1p(series)
    log_ref  = np.log1p(REFERENCE_MAX)
    return (log_vals / log_ref).clip(0, 1)


def risk_tier(score: float) -> str:
    if score >= 20.5: return "critical"
    elif score >= 15.8: return "high"
    elif score >= 8.5: return "medium"
    else: return "low"


def load_live_ais() -> pd.DataFrame | None:
    """Load most recent live AIS parquet file."""
    files = sorted(AIS_DIR.glob("live_*.parquet"), reverse=True)
    if not files:
        logger.warning("No live AIS files found")
        return None

    latest = files[0]
    df = pd.read_parquet(latest)
    logger.info(f"Loaded live AIS: {len(df)} records from {latest.name}")

    # Clean
    df = df.dropna(subset=["lat", "lon"])
    df["speed_knots"] = pd.to_numeric(df["speed_knots"], errors="coerce").fillna(0)
    df = df[df["speed_knots"] <= MAX_REALISTIC_SPEED]
    df = df[df["lat"].between(24, 47) & df["lon"].between(-82, -60)]

    return df


def load_whale_presence(month: int) -> pd.DataFrame | None:
    """Load whale presence layer for the current month."""
    path = PROCESSED_DIR / f"whale_presence_{month:02d}.parquet"
    if not path.exists():
        logger.warning(f"No whale presence file for month {month}")
        return None
    return pd.read_parquet(path)


def build_live_risk() -> None:
    now   = datetime.now(timezone.utc)
    month = now.month

    logger.info(f"Building live risk grid — {now.strftime('%Y-%m-%d %H:%M UTC')}")

    # Load live vessels
    ais = load_live_ais()
    if ais is None or ais.empty:
        logger.warning("No live AIS data — skipping live risk build")
        return

    # Snap to grid and aggregate
    ais["vt_weight"] = ais.get("vessel_type", pd.Series(dtype=str)).apply(
        lambda x: get_vessel_weight(x) if pd.notna(x) else 0.5
    ).astype(float)
    ais = snap_to_grid(ais)

    agg = ais.groupby("cell_id").agg(
        lat=("cell_lat", "first"),
        lon=("cell_lon", "first"),
        vessel_count=("mmsi", "count"),
        mean_speed_knots=("speed_knots", "mean"),
        vessel_type_weight=("vt_weight", "mean"),
    ).reset_index()
    agg["vessel_type_weight"] = agg["vessel_type_weight"].fillna(0.5)
    agg["mean_speed_knots"]   = agg["mean_speed_knots"].fillna(0.0)

    agg["speed_factor"]     = agg["mean_speed_knots"].apply(speed_factor)
    agg["shipping_density"] = normalize_live_density(agg["vessel_count"])

    logger.info(f"  Live vessels aggregated: {len(agg)} occupied cells")

    # Load whale presence for current month
    presence = load_whale_presence(month)
    if presence is None:
        logger.warning("No whale presence data — using shipping signal only")
        agg["whale_presence_prob"] = 0.5  # neutral fallback
        agg["species_present"]     = ""
    else:
        agg = agg.merge(
            presence[["cell_id", "whale_presence_prob", "species_present"]],
            on="cell_id",
            how="left",
        )
        agg["whale_presence_prob"] = agg["whale_presence_prob"].fillna(0.0)
        agg["species_present"]     = agg["species_present"].fillna("")

    # Risk formula
    density  = agg["shipping_density"].clip(0, 1)
    speed    = agg["speed_factor"].clip(0, 1)
    vtype    = agg["vessel_type_weight"].clip(0, 1)
    whale    = agg["whale_presence_prob"].clip(0, 1)

    modifier            = (speed + vtype) / 2
    agg["risk_score"]   = (density * modifier * whale * 100).fillna(0.0).round(4)
    agg["risk_tier"]    = agg["risk_score"].apply(risk_tier)
    agg["month"]        = month
    agg["generated_at"] = now.isoformat()
    agg["is_live"]      = True

    # Final column order
    cols = [
        "cell_id", "lat", "lon", "month",
        "vessel_count", "mean_speed_knots",
        "shipping_density", "speed_factor", "vessel_type_weight",
        "whale_presence_prob", "species_present",
        "risk_score", "risk_tier",
        "generated_at", "is_live",
    ]
    agg = agg[[c for c in cols if c in agg.columns]]

    agg.to_parquet(OUT_PATH, index=False)

    n_active = (agg["risk_score"] > 0.01).sum()
    tiers    = agg["risk_tier"].value_counts().to_dict()
    logger.success(
        f"Live risk grid saved → {OUT_PATH.name} | "
        f"{len(agg)} cells, {n_active} active | "
        f"max={agg['risk_score'].max():.1f} | tiers={tiers}"
    )


if __name__ == "__main__":
    build_live_risk()
