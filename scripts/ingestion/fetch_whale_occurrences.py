"""
fetch_whale_occurrences.py
--------------------------
Downloads whale occurrence records from GBIF and OBIS for the four target
species, clips to NARW habitat bounding boxes, and saves cleaned Parquet
files to data/raw/whale_occurrences/.

Usage (run from backend/):
    python ../scripts/ingestion/fetch_whale_occurrences.py

Outputs:
    data/raw/whale_occurrences/<species_key>_occurrences.parquet

Data sources:
    GBIF: https://api.gbif.org/v1/occurrence/search  (no key required)
    OBIS: https://api.obis.org/v3/occurrence         (no key required)
"""

import sys
import time
from pathlib import Path
from datetime import datetime

import httpx
import pandas as pd
from loguru import logger

# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.utils.species import SPECIES

# ── Config ────────────────────────────────────────────────────────────────────

# Bounding boxes (min_lon, min_lat, max_lon, max_lat) — same as AIS ingestion
BBOXES = {
    "gulf_of_maine":      (-76.0, 40.0, -60.0, 50.0),
    "southeast_us":       (-82.0, 24.0, -76.0, 32.0),
    "santa_barbara":      (-122.0, 32.0, -117.0, 35.5),
    "gulf_farallones":    (-124.0, 36.5, -121.0, 38.5),
    "san_pedro_channel":  (-120.5, 32.5, -117.0, 34.5),
}

# Year range to pull occurrences for
YEAR_START = 2010
YEAR_END   = 2024

# Max records per species per source (GBIF paginates at 300/request)
GBIF_PAGE_SIZE = 300
GBIF_MAX_RECORDS = 10_000  # stay well within free tier

OBIS_PAGE_SIZE = 5000
OBIS_MAX_RECORDS = 10_000

# Seconds to wait between API requests (be polite)
REQUEST_DELAY = 0.5

# Output directory
OUT_DIR = REPO_ROOT / "data" / "raw" / "whale_occurrences"


# ── GBIF ──────────────────────────────────────────────────────────────────────

def fetch_gbif_species(
    species_key: str,
    taxon_key: int,
    bbox: tuple[float, float, float, float],
    bbox_name: str,
) -> list[dict]:
    """
    Fetch occurrence records from GBIF for one species + one bounding box.
    Paginates through all results up to GBIF_MAX_RECORDS.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    base_url = "https://api.gbif.org/v1/occurrence/search"

    params = {
        "taxonKey": taxon_key,
        "decimalLatitude": f"{min_lat},{max_lat}",
        "decimalLongitude": f"{min_lon},{max_lon}",
        "year": f"{YEAR_START},{YEAR_END}",
        "hasCoordinate": "true",
        "hasGeospatialIssue": "false",
        "limit": GBIF_PAGE_SIZE,
        "offset": 0,
    }

    rows = []
    while len(rows) < GBIF_MAX_RECORDS:
        try:
            r = httpx.get(base_url, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.warning(f"  GBIF request failed: {e}")
            break

        results = data.get("results", [])
        for rec in results:
            lat = rec.get("decimalLatitude")
            lon = rec.get("decimalLongitude")
            if lat is None or lon is None:
                continue
            rows.append({
                "species_code": species_key.upper(),
                "scientific_name": rec.get("species", rec.get("scientificName", "")),
                "lat": float(lat),
                "lon": float(lon),
                "date": rec.get("eventDate", ""),
                "source": "GBIF",
                "record_type": rec.get("basisOfRecord", "").lower(),
                "individual_count": rec.get("individualCount"),
                "gbif_key": rec.get("key"),
                "bbox_region": bbox_name,
            })

        end_of_records = data.get("endOfRecords", True)
        total = data.get("count", 0)
        logger.debug(f"    GBIF page offset={params['offset']} — {len(results)} records (total={total})")

        if end_of_records or not results:
            break

        params["offset"] += GBIF_PAGE_SIZE
        time.sleep(REQUEST_DELAY)

    return rows


def fetch_gbif(species_key: str, taxon_key: int) -> pd.DataFrame:
    """Fetch GBIF records across all bounding boxes for one species."""
    all_rows = []
    for bbox_name, bbox in BBOXES.items():
        logger.info(f"  GBIF {species_key} — {bbox_name}")
        rows = fetch_gbif_species(species_key, taxon_key, bbox, bbox_name)
        logger.info(f"    → {len(rows):,} records")
        all_rows.extend(rows)
        time.sleep(REQUEST_DELAY)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df = df.drop_duplicates(subset=["lat", "lon", "date", "source"])
    return df


# ── OBIS ──────────────────────────────────────────────────────────────────────

def fetch_obis_species(
    species_key: str,
    aphia_id: int,
    bbox: tuple[float, float, float, float],
    bbox_name: str,
) -> list[dict]:
    """
    Fetch occurrence records from OBIS for one species + one bounding box.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    base_url = "https://api.obis.org/v3/occurrence"

    params = {
        "taxonid": aphia_id,
        "geometry": f"POLYGON(({min_lon} {min_lat},{max_lon} {min_lat},{max_lon} {max_lat},{min_lon} {max_lat},{min_lon} {min_lat}))",
        "startdate": f"{YEAR_START}-01-01",
        "enddate":   f"{YEAR_END}-12-31",
        "size": OBIS_PAGE_SIZE,
        "after": None,
    }

    rows = []
    page = 0
    while len(rows) < OBIS_MAX_RECORDS:
        # OBIS uses cursor-based pagination via 'after' param
        fetch_params = {k: v for k, v in params.items() if v is not None}
        try:
            r = httpx.get(base_url, params=fetch_params, timeout=60)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.warning(f"  OBIS request failed: {e}")
            break

        results = data.get("results", [])
        for rec in results:
            lat = rec.get("decimalLatitude")
            lon = rec.get("decimalLongitude")
            if lat is None or lon is None:
                continue
            rows.append({
                "species_code": species_key.upper(),
                "scientific_name": rec.get("scientificName", ""),
                "lat": float(lat),
                "lon": float(lon),
                "date": rec.get("eventDate", ""),
                "source": "OBIS",
                "record_type": rec.get("basisOfRecord", "").lower(),
                "individual_count": rec.get("individualCount"),
                "obis_id": rec.get("id"),
                "bbox_region": bbox_name,
            })

        page += 1
        total = data.get("total", 0)
        logger.debug(f"    OBIS page {page} — {len(results)} records (total={total})")

        # OBIS returns fewer than size when done
        if len(results) < OBIS_PAGE_SIZE:
            break

        # Use the last record's id as cursor
        if results:
            params["after"] = results[-1].get("id")
        time.sleep(REQUEST_DELAY)

    return rows


def fetch_obis(species_key: str, aphia_id: int) -> pd.DataFrame:
    """Fetch OBIS records across all bounding boxes for one species."""
    all_rows = []
    for bbox_name, bbox in BBOXES.items():
        logger.info(f"  OBIS {species_key} — {bbox_name}")
        rows = fetch_obis_species(species_key, aphia_id, bbox, bbox_name)
        logger.info(f"    → {len(rows):,} records")
        all_rows.extend(rows)
        time.sleep(REQUEST_DELAY)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df = df.drop_duplicates(subset=["lat", "lon", "date", "source"])
    return df


# ── Cleaning ──────────────────────────────────────────────────────────────────

def clean(df: pd.DataFrame, species_key: str) -> pd.DataFrame:
    """Standardise columns, parse dates, add month column."""
    if df.empty:
        return df

    # Parse date — GBIF uses ISO8601, OBIS can be partial (YYYY or YYYY-MM)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date.astype(str)

    # Extract month for seasonal analysis
    df["month"] = pd.to_datetime(df["date"], errors="coerce").dt.month

    # Normalise record_type
    df["record_type"] = df["record_type"].str.lower().str.replace("_", " ")

    # Drop rows with no valid position
    df = df.dropna(subset=["lat", "lon"])
    df = df[(df["lat"].between(-90, 90)) & (df["lon"].between(-180, 180))]

    # Final column order
    cols = [
        "species_code", "scientific_name",
        "lat", "lon",
        "date", "month",
        "source", "record_type",
        "individual_count", "bbox_region",
    ]
    # Only keep columns that exist
    cols = [c for c in cols if c in df.columns]
    df = df[cols].reset_index(drop=True)

    logger.info(f"  Cleaned {species_key}: {len(df):,} records, months: {sorted(df['month'].dropna().unique().tolist())}")
    return df


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_species(species_key: str) -> None:
    sp = SPECIES[species_key]
    out_path = OUT_DIR / f"{species_key}_occurrences.parquet"

    if out_path.exists():
        logger.info(f"{species_key} already fetched — skipping ({out_path.name})")
        return

    logger.info(f"── {sp.common_name} ({sp.scientific_name}) ──")

    gbif_df  = fetch_gbif(species_key, sp.gbif_taxon_key)
    obis_df  = fetch_obis(species_key, sp.obis_aphia_id)

    combined = pd.concat([gbif_df, obis_df], ignore_index=True)
    combined = clean(combined, species_key)

    if combined.empty:
        logger.warning(f"  No records found for {species_key}")
        return

    combined.to_parquet(out_path, index=False)
    logger.success(f"  Saved {len(combined):,} records → {out_path.name}")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output: {OUT_DIR}")
    logger.info(f"Year range: {YEAR_START}–{YEAR_END}")
    logger.info(f"Species: {list(SPECIES.keys())}")

    for key in SPECIES:
        fetch_species(key)

    logger.success("All species complete.")
    logger.info("Summary:")
    for f in sorted(OUT_DIR.glob("*.parquet")):
        df = pd.read_parquet(f)
        size_kb = f.stat().st_size / 1000
        logger.info(f"  {f.name}: {len(df):,} records ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()