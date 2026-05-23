"""
build_shipping_density.py
--------------------------
Step 2.2 — Shipping density layer.
 
Aggregates AIS position records onto the 0.1° ocean grid, computing per cell:
  - vessel count (log-normalized to 0–1 shipping density score)
  - mean speed over ground (knots)
  - vessel speed factor (0–1, based on NOAA strike-risk thresholds)
  - vessel type weight (0–1, weighted by strike risk per vessel class)
 
Log normalization is used for vessel count because AIS data is highly skewed —
major ports dominate raw counts, compressing all other cells to near-zero
under min-max scaling.
 
Usage (run from backend/):
    python ../scripts/processing/build_shipping_density.py
 
Outputs:
    data/processed/shipping_density_<MM>.parquet  (one per month)
"""
 
import sys
from pathlib import Path
 
import numpy as np
import pandas as pd
from loguru import logger
 
# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))
 
# ── Paths ─────────────────────────────────────────────────────────────────────
AIS_DIR   = REPO_ROOT / "data" / "raw" / "ais"
GRID_PATH = REPO_ROOT / "data" / "processed" / "grid_cells.parquet"
OUT_DIR   = REPO_ROOT / "data" / "processed"
 
# ── Constants ─────────────────────────────────────────────────────────────────
 
def speed_factor(knots: float) -> float:
    if knots <= 10:
        return 0.3
    elif knots <= 14:
        return 0.6
    else:
        return 1.0
 
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
 
MAX_REALISTIC_SPEED = 40.0
 
 
# ── Helpers ───────────────────────────────────────────────────────────────────
 
def get_vessel_weight(type_code) -> float:
    try:
        code = int(type_code)
    except (ValueError, TypeError):
        return 0.5
    if code in VESSEL_TYPE_WEIGHTS:
        return VESSEL_TYPE_WEIGHTS[code]
    bucket = (code // 10) * 10
    return VESSEL_TYPE_WEIGHTS.get(bucket, 0.5)
 
 
def snap_to_grid(df: pd.DataFrame, resolution: float = 0.1) -> pd.DataFrame:
    half = resolution / 2
    df["cell_lat"] = (np.floor(df["lat"] / resolution) * resolution + half).round(6)
    df["cell_lon"] = (np.floor(df["lon"] / resolution) * resolution + half).round(6)
    df["cell_id"]  = df["cell_lat"].round(2).astype(str) + "_" + df["cell_lon"].round(2).astype(str)
    return df
 
 
def log_normalize(series: pd.Series) -> pd.Series:
    """
    Log-normalize a skewed count distribution to 0–1.
    Uses log1p so zeros stay zero, then min-max scales the log values.
    This prevents one dominant port from compressing all other cells to ~0.
    """
    log_vals = np.log1p(series)
    mn, mx = log_vals.min(), log_vals.max()
    if mx == mn:
        return pd.Series(0.0, index=series.index)
    return (log_vals - mn) / (mx - mn)
 
 
# ── Core computation ──────────────────────────────────────────────────────────
 
def compute_density(ais: pd.DataFrame, month: int) -> pd.DataFrame:
    df = ais[ais["timestamp"].dt.month == month].copy()
    logger.info(f"  Month {month:02d}: {len(df):,} AIS records")
 
    if df.empty:
        return pd.DataFrame()
 
    df = df[df["speed_knots"] <= MAX_REALISTIC_SPEED]
    df["vt_weight"] = df["vessel_type"].apply(get_vessel_weight)
    df = snap_to_grid(df)
 
    agg = df.groupby("cell_id").agg(
        lat=("cell_lat", "first"),
        lon=("cell_lon", "first"),
        vessel_count=("mmsi", "count"),
        mean_speed_knots=("speed_knots", "mean"),
        vessel_type_weight=("vt_weight", "mean"),
    ).reset_index()
 
    agg["speed_factor"]    = agg["mean_speed_knots"].apply(speed_factor)
    agg["shipping_density"] = log_normalize(agg["vessel_count"])
    agg["month"] = month
 
    float_cols = ["mean_speed_knots", "vessel_type_weight", "speed_factor", "shipping_density"]
    agg[float_cols] = agg[float_cols].round(4)
 
    logger.info(f"  → {len(agg):,} occupied cells")
    logger.info(f"    Density range:  {agg['shipping_density'].min():.3f} – {agg['shipping_density'].max():.3f}")
    logger.info(f"    Density p50:    {agg['shipping_density'].median():.3f}  p75: {agg['shipping_density'].quantile(0.75):.3f}  p90: {agg['shipping_density'].quantile(0.90):.3f}")
    logger.info(f"    Speed range:    {agg['mean_speed_knots'].min():.1f} – {agg['mean_speed_knots'].max():.1f} kn")
    logger.info(f"    Speed factors:  slow={( agg['speed_factor'] == 0.3).sum():,}  med={(agg['speed_factor'] == 0.6).sum():,}  fast={(agg['speed_factor'] == 1.0).sum():,}")
 
    return agg
 
 
def merge_with_grid(density: pd.DataFrame, grid: pd.DataFrame, month: int) -> pd.DataFrame:
    merged = grid[["cell_id", "lat", "lon"]].merge(density, on="cell_id", how="left")
    merged["month"]              = month
    merged["vessel_count"]       = merged["vessel_count"].fillna(0).astype(int)
    merged["mean_speed_knots"]   = merged["mean_speed_knots"].fillna(0.0)
    merged["speed_factor"]       = merged["speed_factor"].fillna(0.0)
    merged["vessel_type_weight"] = merged["vessel_type_weight"].fillna(0.0)
    merged["shipping_density"]   = merged["shipping_density"].fillna(0.0)
 
    merged["lat"] = merged["lat_x"].combine_first(merged["lat_y"])
    merged["lon"] = merged["lon_x"].combine_first(merged["lon_y"])
    merged = merged.drop(columns=["lat_x", "lat_y", "lon_x", "lon_y"], errors="ignore")
 
    return merged[[
        "cell_id", "lat", "lon", "month",
        "vessel_count", "mean_speed_knots",
        "speed_factor", "vessel_type_weight", "shipping_density",
    ]]
 
 
# ── Main ──────────────────────────────────────────────────────────────────────
 
def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
 
    # Remove old density files so we recompute with log normalization
    for old in OUT_DIR.glob("shipping_density_*.parquet"):
        old.unlink()
        logger.info(f"Removed stale {old.name}")
 
    grid = pd.read_parquet(GRID_PATH)
    logger.info(f"Grid: {len(grid):,} ocean cells")
 
    ais_files = sorted(AIS_DIR.glob("AIS_*.parquet"))
    logger.info(f"AIS files: {[f.name for f in ais_files]}")
 
    all_ais = pd.concat(
        [pd.read_parquet(f) for f in ais_files],
        ignore_index=True,
    )
    all_ais["timestamp"] = pd.to_datetime(all_ais["timestamp"], errors="coerce")
    all_ais = all_ais.dropna(subset=["timestamp", "lat", "lon"])
    logger.info(f"Total AIS records: {len(all_ais):,}")
 
    months = sorted(all_ais["timestamp"].dt.month.dropna().unique().astype(int).tolist())
    logger.info(f"Months in AIS data: {months}")
 
    for month in months:
        out_path = OUT_DIR / f"shipping_density_{month:02d}.parquet"
        logger.info(f"── Computing density for month {month:02d} ──")
        density = compute_density(all_ais, month)
        if density.empty:
            logger.warning(f"  No data for month {month:02d} — skipping")
            continue
        merged = merge_with_grid(density, grid, month)
        merged.to_parquet(out_path, index=False)
        n_active = (merged["vessel_count"] > 0).sum()
        logger.success(f"  Saved → {out_path.name} ({n_active:,} active cells)")
 
    logger.success("Step 2.2 complete — shipping density layers ready (log-normalized).")
 
 
if __name__ == "__main__":
    main()