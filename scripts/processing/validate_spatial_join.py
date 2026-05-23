"""
validate_spatial_join.py
------------------------
Step 1.6 — Spatial join validation.

Overlays all ingested datasets against each other to confirm alignment
before building the risk score engine. Produces a validation report
and flags any data quality issues.

Checks performed:
  1. Strike incidents vs SMA zones  — what % of strikes fall inside a zone?
  2. Strike incidents vs whale occurrences — are occurrences dense near strikes?
  3. AIS data quality — speed outliers, vessel type coverage, spatial distribution
  4. Whale occurrence coverage — records per species per month

Target: ≥70% of curated strikes should fall inside or within 50km of an SMA zone.

Usage (run from backend/):
    python ../scripts/processing/validate_spatial_join.py

Outputs:
    data/processed/validation_report.json  — machine-readable results
    data/processed/validation_report.txt   — human-readable summary
"""

import json
import sys
from pathlib import Path
from datetime import datetime

import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point
from loguru import logger

# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# ── Paths ─────────────────────────────────────────────────────────────────────
AIS_DIR        = REPO_ROOT / "data" / "raw" / "ais"
WHALE_DIR      = REPO_ROOT / "data" / "raw" / "whale_occurrences"
INCIDENTS_PATH = REPO_ROOT / "data" / "raw" / "incidents" / "strike_incidents.parquet"
ZONES_PATH     = REPO_ROOT / "data" / "shapefiles" / "narw_sma_zones.parquet"
OUT_DIR        = REPO_ROOT / "data" / "processed"

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_REALISTIC_SPEED = 40.0   # knots — anything above is bad AIS data
STRIKE_ZONE_BUFFER_KM = 50   # strikes within this distance count as "near" a zone


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_incidents() -> gpd.GeoDataFrame:
    df = pd.read_parquet(INCIDENTS_PATH)
    # Only use curated static strikes for spatial validation (known good coords)
    df = df[~df["source"].str.contains("OBIS", na=False)]
    gdf = gpd.GeoDataFrame(
        df,
        geometry=[Point(row.lon, row.lat) for _, row in df.iterrows()],
        crs="EPSG:4326",
    )
    logger.info(f"Loaded {len(gdf)} curated strike incidents")
    return gdf


def load_zones() -> gpd.GeoDataFrame:
    gdf = gpd.read_parquet(ZONES_PATH)
    gdf = gdf.set_crs("EPSG:4326", allow_override=True)
    logger.info(f"Loaded {len(gdf)} SMA zones")
    return gdf


def load_whale_occurrences() -> pd.DataFrame:
    frames = []
    for f in sorted(WHALE_DIR.glob("*_occurrences.parquet")):
        df = pd.read_parquet(f)
        frames.append(df)
    if not frames:
        logger.warning("No whale occurrence files found")
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    logger.info(f"Loaded {len(combined):,} whale occurrence records")
    return combined


def load_ais() -> pd.DataFrame:
    frames = []
    for f in sorted(AIS_DIR.glob("AIS_*.parquet")):
        df = pd.read_parquet(f)
        frames.append(df)
    if not frames:
        logger.warning("No AIS files found")
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    logger.info(f"Loaded {len(combined):,} AIS position records")
    return combined


# ── Check 1: Strikes vs SMA Zones ────────────────────────────────────────────

def check_strikes_vs_zones(
    incidents: gpd.GeoDataFrame,
    zones: gpd.GeoDataFrame,
) -> dict:
    logger.info("Check 1: Strike incidents vs SMA zones")

    # Project to metres for buffer
    incidents_m = incidents.to_crs("EPSG:3857")
    zones_m     = zones.to_crs("EPSG:3857")
    zones_buffered = zones_m.copy()
    zones_buffered["geometry"] = zones_m.geometry.buffer(STRIKE_ZONE_BUFFER_KM * 1000)

    # Point-in-polygon (exact)
    joined_exact = gpd.sjoin(incidents, zones, how="left", predicate="within")
    in_zone = joined_exact["index_right"].notna()
    n_in_zone = int(in_zone.sum())

    # Within buffer
    joined_buffer = gpd.sjoin(incidents_m, zones_buffered, how="left", predicate="within")
    near_zone = joined_buffer["index_right"].notna()
    n_near_zone = int(near_zone.sum())

    total = len(incidents)
    pct_exact  = n_in_zone  / total * 100
    pct_buffer = n_near_zone / total * 100

    logger.info(f"  {n_in_zone}/{total} strikes inside SMA zones ({pct_exact:.1f}%)")
    logger.info(f"  {n_near_zone}/{total} strikes within {STRIKE_ZONE_BUFFER_KM}km of zone ({pct_buffer:.1f}%)")

    # Strikes per zone
    zone_counts = (
        joined_exact.dropna(subset=["index_right"])
        .groupby("zone_name")
        .size()
        .sort_values(ascending=False)
        .to_dict()
    )

    # Strikes outside all zones
    outside = incidents[~in_zone][["incident_id", "species_code", "lat", "lon", "year"]].to_dict("records")

    result = {
        "total_curated_strikes": total,
        "strikes_inside_sma_zone": n_in_zone,
        "strikes_within_50km_of_zone": n_near_zone,
        "pct_inside_zone": round(pct_exact, 1),
        "pct_near_zone": round(pct_buffer, 1),
        "target_met": pct_buffer >= 70.0,
        "strikes_per_zone": zone_counts,
        "strikes_outside_zones": outside,
    }

    status = "✅ PASS" if result["target_met"] else "⚠️  BELOW TARGET"
    logger.info(f"  Target (≥70% near zone): {status}")
    return result


# ── Check 2: Strikes vs Whale Occurrences ─────────────────────────────────────

def check_strikes_vs_occurrences(
    incidents: gpd.GeoDataFrame,
    occurrences: pd.DataFrame,
) -> dict:
    logger.info("Check 2: Strike locations vs whale occurrence density")

    if occurrences.empty:
        return {"status": "skipped", "reason": "no occurrence data"}

    # Round to 1° grid for density check (coarser than risk grid for this check)
    occ = occurrences.copy()
    occ["grid_lat"] = occ["lat"].round(0)
    occ["grid_lon"] = occ["lon"].round(0)
    density = occ.groupby(["grid_lat", "grid_lon"]).size().reset_index(name="occ_count")

    # For each strike, find occurrence density at same 1° cell
    inc = incidents.copy()
    inc["grid_lat"] = inc["lat"].round(0)
    inc["grid_lon"] = inc["lon"].round(0)
    inc = inc.merge(density, on=["grid_lat", "grid_lon"], how="left")

    n_with_occ = int(inc["occ_count"].notna().sum())
    n_total    = len(inc)
    median_occ = float(inc["occ_count"].median()) if n_with_occ > 0 else 0

    logger.info(f"  {n_with_occ}/{n_total} strike cells have whale occurrence records")
    logger.info(f"  Median occurrence count at strike cells: {median_occ:.0f}")

    return {
        "total_strikes": n_total,
        "strikes_with_occurrence_records": n_with_occ,
        "pct_with_occurrences": round(n_with_occ / n_total * 100, 1),
        "median_occurrences_at_strike_cell": median_occ,
    }


# ── Check 3: AIS Data Quality ─────────────────────────────────────────────────

def check_ais_quality(ais: pd.DataFrame) -> dict:
    logger.info("Check 3: AIS data quality")

    if ais.empty:
        return {"status": "skipped", "reason": "no AIS data"}

    total = len(ais)

    # Speed outliers
    outliers = ais[ais["speed_knots"] > MAX_REALISTIC_SPEED]
    n_outliers = len(outliers)
    pct_outliers = n_outliers / total * 100

    # Speed distribution
    clean = ais[ais["speed_knots"] <= MAX_REALISTIC_SPEED]
    speed_bins = {
        "slow_0_10kn":    int((clean["speed_knots"] <= 10).sum()),
        "medium_10_14kn": int(clean["speed_knots"].between(10, 14).sum()),
        "fast_14plus_kn": int((clean["speed_knots"] > 14).sum()),
    }

    # Vessel type coverage
    type_counts = (
        ais["vessel_type"]
        .dropna()
        .astype(int)
        .value_counts()
        .head(10)
        .to_dict()
    )
    type_counts = {str(k): int(v) for k, v in type_counts.items()}

    # Spatial coverage
    lat_range = (float(ais["lat"].min()), float(ais["lat"].max()))
    lon_range = (float(ais["lon"].min()), float(ais["lon"].max()))

    # Months covered
    months = sorted(ais["timestamp"].dt.month.dropna().unique().tolist())

    logger.info(f"  Total records: {total:,}")
    logger.info(f"  Speed outliers (>{MAX_REALISTIC_SPEED}kn): {n_outliers:,} ({pct_outliers:.2f}%)")
    logger.info(f"  Speed bins: {speed_bins}")
    logger.info(f"  Lat range: {lat_range}, Lon range: {lon_range}")
    logger.info(f"  Months covered: {months}")

    return {
        "total_records": total,
        "speed_outliers": n_outliers,
        "pct_speed_outliers": round(pct_outliers, 2),
        "speed_distribution": speed_bins,
        "top_vessel_types": type_counts,
        "lat_range": lat_range,
        "lon_range": lon_range,
        "months_covered": months,
        "recommendation": (
            f"Filter speed_knots > {MAX_REALISTIC_SPEED} before risk scoring"
            if n_outliers > 0 else "Speed data looks clean"
        ),
    }


# ── Check 4: Whale Occurrence Coverage ───────────────────────────────────────

def check_occurrence_coverage(occurrences: pd.DataFrame) -> dict:
    logger.info("Check 4: Whale occurrence coverage")

    if occurrences.empty:
        return {"status": "skipped", "reason": "no occurrence data"}

    summary = {}
    for species, grp in occurrences.groupby("species_code"):
        months = sorted(grp["month"].dropna().unique().tolist())
        sources = grp["source"].value_counts().to_dict()
        summary[species] = {
            "total_records": len(grp),
            "months_with_data": [int(m) for m in months],
            "missing_months": [m for m in range(1, 13) if m not in months],
            "sources": {str(k): int(v) for k, v in sources.items()},
        }
        logger.info(
            f"  {species}: {len(grp):,} records, "
            f"months {months}, "
            f"sources {list(sources.keys())}"
        )

    return summary


# ── Report writer ─────────────────────────────────────────────────────────────

def write_report(results: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = OUT_DIR / "validation_report.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.success(f"Saved JSON report → {json_path}")

    # Human-readable text
    txt_path = OUT_DIR / "validation_report.txt"
    lines = [
        "=" * 60,
        "WHALE STRIKE RISK NAVIGATOR — STEP 1.6 VALIDATION REPORT",
        f"Generated: {results['generated_at']}",
        "=" * 60,
        "",
        "── CHECK 1: Strikes vs SMA Zones ──────────────────────────",
        f"  Curated strikes:            {results['strikes_vs_zones']['total_curated_strikes']}",
        f"  Inside SMA zone (exact):    {results['strikes_vs_zones']['strikes_inside_sma_zone']} ({results['strikes_vs_zones']['pct_inside_zone']}%)",
        f"  Within 50km of zone:        {results['strikes_vs_zones']['strikes_within_50km_of_zone']} ({results['strikes_vs_zones']['pct_near_zone']}%)",
        f"  Target (≥70%):              {'PASS ✅' if results['strikes_vs_zones']['target_met'] else 'BELOW TARGET ⚠️'}",
        "",
        "  Strikes per zone:",
    ]
    for zone, count in results["strikes_vs_zones"].get("strikes_per_zone", {}).items():
        lines.append(f"    {zone}: {count}")

    lines += [
        "",
        "── CHECK 2: Strikes vs Whale Occurrences ──────────────────",
        f"  Strikes with occurrence records: {results['strikes_vs_occurrences'].get('strikes_with_occurrence_records', 'N/A')}",
        f"  Pct with occurrences:            {results['strikes_vs_occurrences'].get('pct_with_occurrences', 'N/A')}%",
        f"  Median occurrences at strike:    {results['strikes_vs_occurrences'].get('median_occurrences_at_strike_cell', 'N/A')}",
        "",
        "── CHECK 3: AIS Data Quality ──────────────────────────────",
        f"  Total AIS records:    {results['ais_quality'].get('total_records', 'N/A'):,}" if isinstance(results['ais_quality'].get('total_records'), int) else f"  Total AIS records:    {results['ais_quality'].get('total_records', 'N/A')}",
        f"  Speed outliers:       {results['ais_quality'].get('speed_outliers', 'N/A')} ({results['ais_quality'].get('pct_speed_outliers', 'N/A')}%)",
        f"  Months covered:       {results['ais_quality'].get('months_covered', 'N/A')}",
        f"  Recommendation:       {results['ais_quality'].get('recommendation', 'N/A')}",
        "",
        "── CHECK 4: Whale Occurrence Coverage ─────────────────────",
    ]
    for species, info in results.get("occurrence_coverage", {}).items():
        lines.append(f"  {species}: {info.get('total_records', 0):,} records, missing months: {info.get('missing_months', [])}")

    lines += ["", "=" * 60]

    with open(txt_path, "w") as f:
        f.write("\n".join(lines))

    logger.success(f"Saved text report → {txt_path}")

    # Print to terminal too
    print("\n" + "\n".join(lines))


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logger.info("Starting Step 1.6 — Spatial Join Validation")

    incidents   = load_incidents()
    zones       = load_zones()
    occurrences = load_whale_occurrences()
    ais         = load_ais()

    results = {
        "generated_at": datetime.utcnow().isoformat(),
        "strikes_vs_zones":       check_strikes_vs_zones(incidents, zones),
        "strikes_vs_occurrences": check_strikes_vs_occurrences(incidents, occurrences),
        "ais_quality":            check_ais_quality(ais),
        "occurrence_coverage":    check_occurrence_coverage(occurrences),
    }

    write_report(results)
    logger.success("Step 1.6 complete — validation report written.")


if __name__ == "__main__":
    main()
