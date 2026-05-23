"""
build_risk_scores.py
--------------------
Step 2.4 — Composite risk formula.

Joins the shipping density layer (Step 2.2) and whale presence layer (Step 2.3)
for each month and computes the final risk score per grid cell:

    shipping_component = shipping_density × mean(speed_factor, vessel_type_weight)
    Risk = shipping_component × whale_presence_prob × 100

Normalized to 0–100. Risk tier assigned:
    critical : score >= 75
    high     : score >= 50
    medium   : score >= 25
    low      : score <  25

Usage (run from backend/):
    python ../scripts/processing/build_risk_scores.py

Outputs:
    data/processed/risk_grid_<MM>.parquet   (one per month)
    data/processed/risk_grid_all.parquet    (all months combined)
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
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
OUT_DIR       = PROCESSED_DIR

# ── Constants ─────────────────────────────────────────────────────────────────
ALL_MONTHS = list(range(1, 13))


# ── Risk tier ─────────────────────────────────────────────────────────────────

def risk_tier(score: float) -> str:
    if score >= 20.5:
        return "critical"
    elif score >= 15.8:
        return "high"
    elif score >= 8.5:
        return "medium"
    else:
        return "low"


# ── Core formula ──────────────────────────────────────────────────────────────

def compute_risk(shipping: pd.DataFrame, presence: pd.DataFrame) -> pd.DataFrame:
    """
    Join shipping density and whale presence on cell_id, apply formula,
    return scored DataFrame.
    """
    df = shipping.merge(
        presence[["cell_id", "whale_presence_prob", "kde_score",
                  "zone_overlap", "species_present"]],
        on="cell_id",
        how="left",
    )

    df["whale_presence_prob"] = df["whale_presence_prob"].fillna(0.0)

    # ── Formula ───────────────────────────────────────────────────────────────
    # Density is the base signal. Speed and vessel type are modifiers averaged
    # together (rather than multiplied) to prevent triple-multiplication
    # collapse where all three small fractions produce near-zero scores.
    #
    # Example at a busy cell:
    #   density=0.8, speed_factor=0.6, vessel_type_weight=0.7
    #   modifier = (0.6 + 0.7) / 2 = 0.65
    #   shipping_component = 0.8 × 0.65 = 0.52
    #   risk = 0.52 × whale_prob × 100
    density = df["shipping_density"].clip(0, 1)
    speed   = df["speed_factor"].clip(0, 1)
    vtype   = df["vessel_type_weight"].clip(0, 1)
    whale   = df["whale_presence_prob"].clip(0, 1)

    modifier = (speed + vtype) / 2
    shipping_component = density * modifier
    df["risk_score"] = (shipping_component * whale * 100).round(2)

    # Assign tier
    df["risk_tier"] = df["risk_score"].apply(risk_tier)

    return df


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Delete old risk grid files so we recompute with fixed formula
    for old in PROCESSED_DIR.glob("risk_grid_*.parquet"):
        old.unlink()
        logger.info(f"Removed stale {old.name}")

    all_frames = []

    for month in ALL_MONTHS:
        out_path = OUT_DIR / f"risk_grid_{month:02d}.parquet"

        shipping_path = PROCESSED_DIR / f"shipping_density_{month:02d}.parquet"
        presence_path = PROCESSED_DIR / f"whale_presence_{month:02d}.parquet"

        if not shipping_path.exists():
            logger.warning(f"Month {month:02d}: no shipping density file — skipping")
            continue
        if not presence_path.exists():
            logger.warning(f"Month {month:02d}: no whale presence file — skipping")
            continue

        logger.info(f"── Month {month:02d} ──")
        shipping = pd.read_parquet(shipping_path)
        presence = pd.read_parquet(presence_path)

        df = compute_risk(shipping, presence)

        # Column order
        df = df[[
            "cell_id", "lat", "lon", "month",
            "shipping_density", "speed_factor", "vessel_type_weight",
            "whale_presence_prob", "kde_score", "zone_overlap",
            "risk_score", "risk_tier", "species_present",
        ]]

        df.to_parquet(out_path, index=False)
        all_frames.append(df)

        nonzero = df[df["risk_score"] > 0]
        tiers   = df["risk_tier"].value_counts().to_dict()
        logger.success(
            f"  Saved → {out_path.name}  |  "
            f"max={df['risk_score'].max():.1f}  |  "
            f"mean={nonzero['risk_score'].mean():.1f} (nonzero)  |  "
            f"tiers={tiers}"
        )

    # ── Combined file ─────────────────────────────────────────────────────────
    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        combined_path = OUT_DIR / "risk_grid_all.parquet"
        combined.to_parquet(combined_path, index=False)
        size_mb = combined_path.stat().st_size / 1_000_000

        logger.success(f"\nCombined grid saved → {combined_path.name} ({size_mb:.1f} MB)")
        logger.info(f"  Total rows:     {len(combined):,}")
        logger.info(f"  Months:         {sorted(combined['month'].unique().tolist())}")
        logger.info(f"  Max risk score: {combined['risk_score'].max():.1f}")
        logger.info(f"  Tier breakdown (all months):")
        for tier in ["critical", "high", "medium", "low"]:
            n   = (combined["risk_tier"] == tier).sum()
            pct = n / len(combined) * 100
            logger.info(f"    {tier:10s}: {n:,} cells ({pct:.1f}%)")

        # Top 10 highest risk cells
        top = (
            combined[combined["risk_score"] > 0]
            .sort_values("risk_score", ascending=False)
            .head(10)[["cell_id", "lat", "lon", "month", "risk_score",
                        "risk_tier", "species_present"]]
        )
        logger.info("\n  Top 10 highest-risk cells:")
        for _, row in top.iterrows():
            logger.info(
                f"    {row['cell_id']}  month={row['month']:02d}  "
                f"score={row['risk_score']:.1f}  "
                f"tier={row['risk_tier']}  "
                f"species={row['species_present']}"
            )

    logger.success("\nStep 2.4 complete — risk grid ready.")


if __name__ == "__main__":
    main()
