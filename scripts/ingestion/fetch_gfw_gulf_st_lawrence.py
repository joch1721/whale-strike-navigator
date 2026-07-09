"""
fetch_gfw_gulf_st_lawrence.py
------------------------------
Fetches AIS Vessel Presence data from Global Fishing Watch's 4Wings API
for the Gulf of St. Lawrence — a region with real NARW occurrence data
but zero NOAA AIS coverage (Canadian waters, outside NOAA's US-only feed).

Usage (run from backend/):
    python ../scripts/ingestion/fetch_gfw_gulf_st_lawrence.py

Outputs:
    data/raw/ais_gfw/GFW_gulf_st_lawrence_2024_<MM>.csv  (one file per month)

Data source:
    https://globalfishingwatch.org — 4Wings API, public-global-ais-vessel-presence:v3.0
    Non-commercial research use. Attribution required if published.
"""

import os
import sys
import time
from pathlib import Path

import httpx
import pandas as pd
from dotenv import load_dotenv
from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / "backend" / ".env")
OUT_DIR = REPO_ROOT / "data" / "raw" / "ais_gfw"

GFW_TOKEN = os.environ.get("GFW_API_TOKEN")
if not GFW_TOKEN:
    logger.error("GFW_API_TOKEN not found in environment. Add it to backend/.env")
    sys.exit(1)

BASE_URL = "https://gateway.api.globalfishingwatch.org/v3/4wings/report"

# Gulf of St. Lawrence bounding box, matching the scale of other project bboxes
GULF_ST_LAWRENCE_GEOJSON = {
    "type": "Polygon",
    "coordinates": [[
        [-70.0, 45.0],
        [-56.0, 45.0],
        [-56.0, 51.0],
        [-70.0, 51.0],
        [-70.0, 45.0],
    ]]
}

DATASET = "public-global-fishing-effort:v3.0"  # stopgap - vessel presence needs separate GFW access grant


def fetch_month(month: int) -> pd.DataFrame | None:
    """Fetch one month of gridded AIS vessel presence for the Gulf of St. Lawrence."""
    start = f"2024-{month:02d}-01"
    # crude end-of-month calc; good enough since 4Wings just needs a valid range
    end_month = month + 1 if month < 12 else 1
    end_year = 2024 if month < 12 else 2025
    end = f"{end_year}-{end_month:02d}-01"

    params = {
        "format": "CSV",
        "datasets[0]": DATASET,
        "temporal-resolution": "MONTHLY",
        "spatial-resolution": "LOW",  # 0.1 degree — matches project grid resolution
        "spatial-aggregation": "false",  # want gridded cells, not one summary stat
        "date-range": f"{start},{end}",
    }
    body = {
        "geojson": GULF_ST_LAWRENCE_GEOJSON,
    }
    logger.info(f"── Month {month:02d} ──")
    try:
        r = httpx.post(
            BASE_URL,
            params=params,
            json=body,
            headers={"Authorization": f"Bearer {GFW_TOKEN}"},
            timeout=120,
        )
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.warning(f"  HTTP {e.response.status_code}: {e.response.text[:300]}")
        return None
    except Exception as e:
        logger.warning(f"  Request failed: {e}")
        return None

    try:
        import zipfile
        from io import BytesIO

        with zipfile.ZipFile(BytesIO(r.content)) as zf:
            csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
            if not csv_names:
                logger.warning(f"  No CSV file found in zip. Contents: {zf.namelist()}")
                return None
            with zf.open(csv_names[0]) as f:
                df = pd.read_csv(f)
    except zipfile.BadZipFile:
        try:
            from io import StringIO
            df = pd.read_csv(StringIO(r.text))
        except Exception as e:
            logger.warning(f"  Failed to parse as CSV or zip: {e}")
            logger.warning(f"  Raw response (first 300 chars): {r.text[:300]}")
            return None
    except Exception as e:
        logger.warning(f"  Failed to parse response: {e}")
        return None

    logger.info(f"  Retrieved {len(df):,} gridded rows")
    return df


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output: {OUT_DIR}")

    for month in range(1, 13):
        out_path = OUT_DIR / f"GFW_gulf_st_lawrence_2024_{month:02d}.csv"
        if out_path.exists():
            logger.info(f"Month {month:02d} already fetched — skipping")
            continue

        df = fetch_month(month)
        if df is None or df.empty:
            logger.warning(f"No data for month {month:02d}")
            continue

        df.to_csv(out_path, index=False)
        logger.success(f"  Saved → {out_path.name} ({len(df):,} rows)")

        # 4Wings only supports one active report at a time per the docs — small delay
        time.sleep(3)

    logger.success("GFW Gulf of St. Lawrence ingestion complete.")


if __name__ == "__main__":
    main()