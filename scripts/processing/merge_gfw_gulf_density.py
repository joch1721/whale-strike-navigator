"""
merge_gfw_gulf_density.py
--------------------------
Merges GFW fishing-effort data into shipping_density_<MM>.parquet for
Gulf of St. Lawrence cells that have zero NOAA AIS coverage.

IMPORTANT LIMITATIONS (documented, not silently assumed):
- This is fishing-vessel effort only (public-global-fishing-effort:v3.0),
  not general cargo/tanker AIS presence. Full AIS Vessel Presence access
  is pending a separate GFW grant.
- No per-vessel speed data exists in this dataset. speed_factor is set to
  a fixed 0.3 (matches the "slow" tier used for ≤10kn elsewhere in the
  model), a conservative default for fishing vessel behavior, not a
  measured value.
- Only fills cells with NO existing NOAA density data — never overwrites
  real NOAA-derived cells.

Usage (run from backend/):
    python ../scripts/processing/merge_gfw_gulf_density.py
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[2]
GFW_DIR = REPO_ROOT / "data" / "raw" / "ais_gfw"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
GRID_PATH = PROCESSED_DIR / "grid_cells.parquet"

# Fixed defaults — no real data exists for these dimensions in this dataset
GFW_SPEED_FACTOR = 0.3        # matches "slow" tier default
GFW_VESSEL_TYPE_WEIGHT = 0.4  # matches existing "fishing" weight


def load_grid() -> pd.DataFrame:
    grid = pd.read_parquet(GRID_PATH)
    logger.info(f"Loaded {len(grid):,} ocean grid cells")
    return grid


def snap_to_grid(gfw_df: pd.DataFrame, grid: pd.DataFrame) -> pd.DataFrame:
    """Snap each GFW lat/lon point to the nearest project grid cell."""
    grid_tree = cKDTree(np.vstack([grid["lon"].values, grid["lat"].values]).T)
    points = np.vstack([gfw_df["Lon"].values, gfw_df["Lat"].values]).T
    dist, idx = grid_tree.query(points, k=1)

    gfw_df = gfw_df.copy()
    gfw_df["cell_id"] = grid.iloc[idx]["cell_id"].values
    gfw_df["snap_dist"] = dist

    # Drop points that snapped too far from any real cell (>0.15° ~ safety margin)
    before = len(gfw_df)
    gfw_df = gfw_df[gfw_df["snap_dist"] < 0.15]
    dropped = before - len(gfw_df)
    if dropped:
        logger.info(f"    Dropped {dropped} points too far from any grid cell")

    return gfw_df


def compute_gfw_density(month: int, grid: pd.DataFrame) -> pd.DataFrame | None:
    path = GFW_DIR / f"GFW_gulf_st_lawrence_2024_{month:02d}.csv"
    if not path.exists():
        return None

    df = pd.read_csv(path)
    df = snap_to_grid(df, grid)

    # Aggregate: unique vessel count per cell (matches NOAA's vessel_count concept)
    agg = (
        df.groupby("cell_id")
        .agg(vessel_count=("Vessel ID", "nunique"),
             total_fishing_hours=("Apparent Fishing Hours", "sum"))
        .reset_index()
    )

    # Log-normalize vessel count, same approach as NOAA density (log1p + min-max)
    log_counts = np.log1p(agg["vessel_count"])
    mn, mx = log_counts.min(), log_counts.max()
    agg["shipping_density"] = (
        (log_counts - mn) / (mx - mn) if mx > mn else 0.0
    )

    agg["month"] = month
    agg["speed_factor"] = GFW_SPEED_FACTOR
    agg["vessel_type_weight"] = GFW_VESSEL_TYPE_WEIGHT
    agg["mean_speed_knots"] = np.nan  # explicitly no real speed data
    agg["source"] = "GFW_fishing_effort"

    return agg[[
        "cell_id", "month", "vessel_count", "mean_speed_knots",
        "speed_factor", "vessel_type_weight", "shipping_density", "source",
    ]]


# NOAA vessel counts below this threshold, within the Gulf bbox, are treated
# as unreliable edge-of-receiver-range noise rather than real coverage —
# NOAA's US-based AIS receivers have no real reach into the Gulf of St.
# Lawrence, so any trace signal there is not meaningful density data.
THIN_SIGNAL_VESSEL_COUNT_THRESHOLD = 10

# Gulf of St. Lawrence bbox — same rectangle used in the GFW fetch script
GULF_LAT_MIN, GULF_LAT_MAX = 45.0, 51.0
GULF_LON_MIN, GULF_LON_MAX = -70.0, -56.0


def merge_into_density_file(month: int, gfw_agg: pd.DataFrame) -> None:
    density_path = PROCESSED_DIR / f"shipping_density_{month:02d}.parquet"
    existing = pd.read_parquet(density_path)

    in_gulf = (
        existing["lat"].between(GULF_LAT_MIN, GULF_LAT_MAX)
        & existing["lon"].between(GULF_LON_MIN, GULF_LON_MAX)
    )
    thin_signal = in_gulf & (existing["vessel_count"] < THIN_SIGNAL_VESSEL_COUNT_THRESHOLD)
    replaceable_cell_ids = set(existing.loc[thin_signal, "cell_id"])

    gfw_agg = gfw_agg.copy()
    lat_lon = gfw_agg["cell_id"].str.split("_", expand=True).astype(float)
    gfw_agg["lat"] = lat_lon[0]
    gfw_agg["lon"] = lat_lon[1]
    gfw_agg = gfw_agg.drop(columns=["source"])

    existing_cells = set(existing["cell_id"])
    brand_new = gfw_agg[~gfw_agg["cell_id"].isin(existing_cells)]
    replacements = gfw_agg[gfw_agg["cell_id"].isin(replaceable_cell_ids)]

    if brand_new.empty and replacements.empty:
        logger.info(f"  Month {month:02d}: no new or replaceable cells "
                    f"(NOAA vessel_count already ≥ {THIN_SIGNAL_VESSEL_COUNT_THRESHOLD} in Gulf area)")
        return

    # Remove rows being replaced, then add both replacements and brand-new cells
    kept = existing[~existing["cell_id"].isin(replaceable_cell_ids)]
    combined = pd.concat([kept, replacements, brand_new], ignore_index=True)
    combined.to_parquet(density_path, index=False)

    logger.success(
        f"  Month {month:02d}: replaced {len(replacements)} thin-signal cells, "
        f"added {len(brand_new)} brand-new cells "
        f"(was {len(existing)}, now {len(combined)})"
    )


def main() -> None:
    grid = load_grid()

    for month in range(1, 13):
        logger.info(f"── Month {month:02d} ──")
        gfw_agg = compute_gfw_density(month, grid)
        if gfw_agg is None or gfw_agg.empty:
            logger.warning(f"  No GFW data for month {month:02d}")
            continue
        merge_into_density_file(month, gfw_agg)

    logger.success("GFW Gulf of St. Lawrence merge complete.")


if __name__ == "__main__":
    main()