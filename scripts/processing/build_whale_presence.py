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

import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point
from loguru import logger
from scipy.spatial import cKDTree


# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# ── Paths ─────────────────────────────────────────────────────────────────────
WHALE_DIR  = REPO_ROOT / "data" / "raw" / "whale_occurrences"
ZONES_PATH = REPO_ROOT / "data" / "shapefiles" / "narw_sma_zones.parquet"
GRID_PATH  = REPO_ROOT / "data" / "processed" / "grid_cells.parquet"
OUT_DIR    = REPO_ROOT / "data" / "processed"

# ── Constants ─────────────────────────────────────────────────────────────────

# KDE bandwidth as an ABSOLUTE isotropic radius in degrees (0.5° ≈ 55 km N–S).
# NOTE: this is a true fixed bandwidth, applied directly by compute_kde_scores().
# It is deliberately NOT passed to scipy's gaussian_kde(bw_method=...), because
# scipy treats a scalar bw_method as a *multiplier on the data covariance*
# (covariance = data_cov * factor**2), not as an absolute distance. That made the
# effective smoothing radius scale with each species' geographic spread — tight
# for clustered NARW, but several degrees wide for Pacific-spread Blue/Fin/Humpback,
# producing high presence scores hundreds of km from any real sighting (cells with
# sample_count == 0 yet kde_score == 1.0). Using the same 0.5° here as in
# compute_sample_counts() keeps kde_score and sample_count on one consistent scale.
#
# Overridable via env var for calibration sweeps, e.g.:
#   KDE_BANDWIDTH=0.75 python ../scripts/processing/build_whale_presence.py
# Default (0.5) is unchanged if the env var isn't set.
KDE_BANDWIDTH = float(os.environ.get("KDE_BANDWIDTH", 0.5))



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

    grid_pts  = np.column_stack([result["lon"].values, result["lat"].values])
    grid_tree = cKDTree(grid_pts)

    # Fixed isotropic Gaussian kernel with an absolute bandwidth in degrees.
    # We evaluate it by hand (not via scipy) so the smoothing radius is truly
    # KDE_BANDWIDTH degrees regardless of how spread out a species' sightings are.
    # Contributions beyond ~4 bandwidths are negligible, so a cKDTree radius query
    # keeps this cheap (most cells have no nearby occurrences and are skipped).
    h          = KDE_BANDWIDTH
    cutoff     = 4.0 * h
    inv_two_h2 = 1.0 / (2.0 * h * h)

    for species, grp in month_occ.groupby("species_code"):
        if len(grp) < MIN_OCCURRENCES:
            logger.debug(f"    {species} month {month}: only {len(grp)} records — skipping KDE")
            continue

        try:
            occ_pts   = np.column_stack([grp["lon"].values, grp["lat"].values])
            occ_tree  = cKDTree(occ_pts)
            neighbors = grid_tree.query_ball_tree(occ_tree, r=cutoff)

            density = np.zeros(len(result))
            for i, nbr in enumerate(neighbors):
                if nbr:
                    diff = occ_pts[nbr] - grid_pts[i]
                    d2   = np.einsum("ij,ij->i", diff, diff)  # squared degree-distance
                    density[i] = np.exp(-d2 * inv_two_h2).sum()

            # Normalize to 0–1 using the 95th percentile of the CELLS THAT HAVE SIGNAL
            # as the ceiling. This still prevents a single dense outlier cluster (e.g.
            # Gulf of St. Lawrence survey effort, which has no AIS coverage) from
            # suppressing signal elsewhere, but — unlike a p95 over all cells — it
            # stays valid now that a tight kernel leaves most of the grid at exactly 0.
            nonzero = density[density > 0]
            if nonzero.size:
                ceiling = np.percentile(nonzero, 95)
                scores = np.clip(density / ceiling, 0, 1) if ceiling > 0 else np.zeros_like(density)
            else:
                scores = np.zeros_like(density)

            # Take max across species (a cell is high-risk if ANY species is present)
            result["kde_score"] = np.maximum(result["kde_score"].values, scores)

            # Track which species contributed
            mask = scores > 0.01  # threshold to avoid noise
            result.loc[mask, "species_present"] = result.loc[mask, "species_present"].apply(
                lambda s: (s + "," + species).strip(",") if species not in s else s
            )

            logger.debug(f"    {species}: fixed-bandwidth KDE on {len(grp)} records, "
                        f"max score={scores.max():.3f}")

        except Exception as e:
            logger.warning(f"    KDE failed for {species} month {month}: {e}")

    n_active = (result["kde_score"] > 0.01).sum()
    logger.info(f"  KDE: {n_active:,} cells with whale presence signal")
    return result


def compute_sample_counts(
    occurrences: pd.DataFrame,
    grid: pd.DataFrame,
    month: int,
) -> pd.Series:
    """
    For each grid cell, count how many occurrence records (across all species)
    fall within one KDE bandwidth radius. This is a rough proxy for how much
    evidence backs that cell's presence score — a cell built from 2 nearby
    sightings shouldn't be visually equivalent to one built from 200.
    """
    month_occ = occurrences[occurrences["month"] == month]
    counts = np.zeros(len(grid), dtype=int)

    if month_occ.empty:
        return pd.Series(counts, index=grid.index)

    grid_tree = cKDTree(np.vstack([grid["lon"].values, grid["lat"].values]).T)

    for species, grp in month_occ.groupby("species_code"):
        occ_tree = cKDTree(np.vstack([grp["lon"].values, grp["lat"].values]).T)
        neighbors = grid_tree.query_ball_tree(occ_tree, r=KDE_BANDWIDTH)
        counts += np.array([len(n) for n in neighbors])

    return pd.Series(counts, index=grid.index)


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

    kde_df["sample_count"] = compute_sample_counts(occurrences, grid, month).values
    kde_df["confidence_tier"] = np.select(
        [kde_df["sample_count"] < 5, kde_df["sample_count"] < 20],
        ["low", "medium"],
        default="high",
    )

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
        "sample_count", "confidence_tier",
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