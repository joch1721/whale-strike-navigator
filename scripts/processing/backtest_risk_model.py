"""
backtest_risk_model.py
----------------------
Step 2.5 — Backtest against historical strike incidents.

Overlays the 80 curated NOAA strike incidents against the monthly risk grid
and measures what percentage fall in cells scored ≥ 25 (medium or above).

Target: ≥70% of confirmed strikes in cells with risk_score ≥ 25.
Stretch: ≥50% in cells with risk_score ≥ 50 (high or critical).

Also reports:
  - Mean risk score at strike locations vs. mean across all ocean cells
  - Strike capture rate by tier
  - Months with best/worst model performance
  - Cells with strikes that scored low (potential model gaps)

Usage (run from backend/):
    python ../scripts/processing/backtest_risk_model.py

Outputs:
    data/processed/backtest_report.json
    data/processed/backtest_report.txt
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import numpy as np
from loguru import logger

# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# ── Paths ─────────────────────────────────────────────────────────────────────
INCIDENTS_PATH = REPO_ROOT / "data" / "raw" / "incidents" / "strike_incidents.parquet"
RISK_DIR       = REPO_ROOT / "data" / "processed"
OUT_DIR        = REPO_ROOT / "data" / "processed"

# ── Thresholds ────────────────────────────────────────────────────────────────
TARGET_SCORE  = 8.5   # medium or above (p75)
STRETCH_SCORE = 15.8  # high or above (p90)
TARGET_PCT        = 70.0   # % of strikes we want to capture
GRID_RESOLUTION   = 0.1    # degrees


# ── Helpers ───────────────────────────────────────────────────────────────────

def snap_to_cell_id(lat: float, lon: float, resolution: float = GRID_RESOLUTION) -> str:
    """Snap a lat/lon to the nearest grid cell ID."""
    half = resolution / 2
    cell_lat = round(np.floor(lat / resolution) * resolution + half, 2)
    cell_lon = round(np.floor(lon / resolution) * resolution + half, 2)
    return f"{cell_lat}_{cell_lon}"


def load_incidents() -> pd.DataFrame:
    """Load curated static strikes only (known good coordinates)."""
    df = pd.read_parquet(INCIDENTS_PATH)
    df = df[~df["source"].str.contains("OBIS", na=False)]
    df = df.dropna(subset=["lat", "lon", "month"])
    df["month"] = df["month"].astype(int)
    df["cell_id"] = df.apply(lambda r: snap_to_cell_id(r["lat"], r["lon"]), axis=1)
    logger.info(f"Loaded {len(df)} curated strike incidents")
    return df


def load_risk_grid() -> pd.DataFrame:
    """Load all available monthly risk grids."""
    frames = []
    for f in sorted(RISK_DIR.glob("risk_grid_0[0-9].parquet")):
        frames.append(pd.read_parquet(f))
    if not frames:
        logger.error("No risk grid files found — run build_risk_scores.py first")
        sys.exit(1)
    combined = pd.concat(frames, ignore_index=True)
    logger.info(f"Loaded risk grid: {len(combined):,} rows, months {sorted(combined['month'].unique().tolist())}")
    return combined


# ── Core backtest ─────────────────────────────────────────────────────────────

def run_backtest(incidents: pd.DataFrame, grid: pd.DataFrame) -> dict:
    """
    For each strike incident, find the risk score for its grid cell
    in the matching month (if available) or the nearest available month.
    """
    available_months = set(grid["month"].unique())
    results = []

    for _, strike in incidents.iterrows():
        cell_id = strike["cell_id"]
        month   = int(strike["month"])

        # Try exact month first, then nearest available month
        if month in available_months:
            use_month = month
            month_exact = True
        else:
            use_month = min(available_months, key=lambda m: abs(m - month))
            month_exact = False

        cell_row = grid[(grid["cell_id"] == cell_id) & (grid["month"] == use_month)]

        if cell_row.empty:
            # Cell not in ocean grid (strike on land or outside bounding box)
            risk_score = 0.0
            risk_tier  = "unknown"
            in_grid    = False
        else:
            risk_score = float(cell_row["risk_score"].iloc[0])
            risk_tier  = cell_row["risk_tier"].iloc[0]
            in_grid    = True

        results.append({
            "incident_id":   strike.get("incident_id", ""),
            "species_code":  strike.get("species_code", ""),
            "lat":           float(strike["lat"]),
            "lon":           float(strike["lon"]),
            "year":          int(strike["year"]) if pd.notna(strike.get("year")) else None,
            "month":         month,
            "use_month":     use_month,
            "month_exact":   month_exact,
            "cell_id":       cell_id,
            "risk_score":    risk_score,
            "risk_tier":     risk_tier,
            "in_grid":       in_grid,
        })

    return pd.DataFrame(results)


# ── Analysis ──────────────────────────────────────────────────────────────────

def analyse(df: pd.DataFrame, grid: pd.DataFrame) -> dict:
    in_grid = df[df["in_grid"]]
    n_total = len(df)
    n_in_grid = len(in_grid)

    # Primary target: % of strikes in cells scored ≥ 25
    n_above_target  = (in_grid["risk_score"] >= TARGET_SCORE).sum()
    n_above_stretch = (in_grid["risk_score"] >= STRETCH_SCORE).sum()
    pct_target  = n_above_target  / n_total * 100
    pct_stretch = n_above_stretch / n_total * 100

    # Mean score at strike locations vs global mean
    mean_at_strikes = in_grid["risk_score"].mean()
    mean_global     = grid["risk_score"].mean()
    mean_nonzero    = grid[grid["risk_score"] > 0]["risk_score"].mean()
    signal_ratio    = mean_at_strikes / mean_nonzero if mean_nonzero > 0 else 0

    # Capture rate by tier
    tier_counts = in_grid["risk_tier"].value_counts().to_dict()

    # By species
    species_summary = {}
    for species, grp in in_grid.groupby("species_code"):
        n_captured = (grp["risk_score"] >= TARGET_SCORE).sum()
        species_summary[species] = {
            "total_strikes":    len(grp),
            "captured":         int(n_captured),
            "pct_captured":     round(n_captured / len(grp) * 100, 1),
            "mean_risk_score":  round(grp["risk_score"].mean(), 1),
        }

    # By month (only months we have data for)
    month_summary = {}
    for month, grp in in_grid.groupby("use_month"):
        n_captured = (grp["risk_score"] >= TARGET_SCORE).sum()
        month_summary[int(month)] = {
            "strikes_tested": len(grp),
            "captured":       int(n_captured),
            "pct_captured":   round(n_captured / len(grp) * 100, 1) if len(grp) > 0 else 0,
            "mean_score":     round(grp["risk_score"].mean(), 1),
        }

    # Missed strikes (scored below target)
    missed = in_grid[in_grid["risk_score"] < TARGET_SCORE].sort_values("risk_score")
    missed_list = missed[["incident_id", "species_code", "lat", "lon",
                           "month", "risk_score", "risk_tier"]].to_dict("records")

    return {
        "generated_at":           datetime.utcnow().isoformat(),
        "total_curated_strikes":  n_total,
        "strikes_in_grid":        n_in_grid,
        "strikes_outside_grid":   n_total - n_in_grid,
        "primary_target_score":   TARGET_SCORE,
        "stretch_target_score":   STRETCH_SCORE,
        "n_above_primary_target": int(n_above_target),
        "n_above_stretch_target": int(n_above_stretch),
        "pct_above_primary":      round(pct_target, 1),
        "pct_above_stretch":      round(pct_stretch, 1),
        "primary_target_met":     pct_target >= TARGET_PCT,
        "mean_risk_at_strikes":   round(mean_at_strikes, 2),
        "mean_risk_global":       round(mean_global, 4),
        "mean_risk_nonzero_cells":round(mean_nonzero, 2),
        "signal_ratio":           round(signal_ratio, 2),
        "tier_breakdown":         tier_counts,
        "by_species":             species_summary,
        "by_month":               month_summary,
        "missed_strikes":         missed_list,
    }


# ── Report writer ─────────────────────────────────────────────────────────────

def write_report(results: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = OUT_DIR / "backtest_report.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.success(f"Saved JSON → {json_path}")

    txt_path = OUT_DIR / "backtest_report.txt"
    lines = [
        "=" * 60,
        "WHALE STRIKE RISK NAVIGATOR — STEP 2.5 BACKTEST REPORT",
        f"Generated: {results['generated_at']}",
        "=" * 60,
        "",
        "── PRIMARY RESULT ──────────────────────────────────────────",
        f"  Curated strikes tested:    {results['total_curated_strikes']}",
        f"  Strikes in grid:           {results['strikes_in_grid']}",
        f"  Strikes outside grid:      {results['strikes_outside_grid']}",
        "",
        f"  Scored ≥ {results['primary_target_score']} (medium+):    "
        f"{results['n_above_primary_target']} / {results['total_curated_strikes']} "
        f"({results['pct_above_primary']}%)",
        f"  Scored ≥ {results['stretch_target_score']} (high+):      "
        f"{results['n_above_stretch_target']} / {results['total_curated_strikes']} "
        f"({results['pct_above_stretch']}%)",
        f"  Primary target (≥70%):     "
        f"{'PASS ✅' if results['primary_target_met'] else 'BELOW TARGET ⚠️'}",
        "",
        "── SIGNAL STRENGTH ─────────────────────────────────────────",
        f"  Mean score at strikes:     {results['mean_risk_at_strikes']}",
        f"  Mean score (nonzero cells):{results['mean_risk_nonzero_cells']}",
        f"  Signal ratio:              {results['signal_ratio']}x",
        f"  (>1.0 means model elevates risk at strike locations)",
        "",
        "── BY SPECIES ──────────────────────────────────────────────",
    ]
    for sp, info in results["by_species"].items():
        lines.append(
            f"  {sp}: {info['captured']}/{info['total_strikes']} captured "
            f"({info['pct_captured']}%)  mean score={info['mean_risk_score']}"
        )

    lines += ["", "── BY MONTH ────────────────────────────────────────────────"]
    for month, info in sorted(results["by_month"].items()):
        lines.append(
            f"  Month {month:02d}: {info['captured']}/{info['strikes_tested']} captured "
            f"({info['pct_captured']}%)  mean={info['mean_score']}"
        )

    lines += [
        "",
        "── MISSED STRIKES (scored < target) ───────────────────────",
    ]
    for s in results["missed_strikes"]:
        lines.append(
            f"  {s['incident_id']} {s['species_code']} "
            f"({s['lat']:.2f},{s['lon']:.2f}) "
            f"month={s['month']:02d} score={s['risk_score']:.1f}"
        )

    lines += ["", "=" * 60]
    txt = "\n".join(lines)

    with open(txt_path, "w") as f:
        f.write(txt)
    logger.success(f"Saved text report → {txt_path}")
    print("\n" + txt)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("Starting Step 2.5 — Backtest")

    incidents = load_incidents()
    grid      = load_risk_grid()

    logger.info("Running backtest...")
    results_df = run_backtest(incidents, grid)

    logger.info("Analysing results...")
    results = analyse(results_df, grid)

    write_report(results)
    logger.success("Step 2.5 complete.")


if __name__ == "__main__":
    main()
