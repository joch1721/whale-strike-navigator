"""
fetch_noaa_ais.py
-----------------
Downloads NOAA MarineCadastre 2024 AIS daily CSV files for the US East Coast
and Gulf of Maine — the primary North Atlantic Right Whale habitat zones.

NOAA publishes daily zipped CSVs (not monthly GeoParquet as originally assumed).
To keep download sizes manageable we sample a few representative days per month
rather than pulling every day. This gives sufficient vessel density coverage
for the risk score engine.

Usage (run from backend/):
    python ../scripts/ingestion/fetch_noaa_ais.py

Outputs:
    data/raw/ais/AIS_2024_<MM>_sampled.parquet  (one file per month)

Data source:
    https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2024/index.html
    Format: daily zipped CSV, ~400 MB uncompressed per day
    Coverage: US waters only. No login required.
"""

import io
import sys
import zipfile
from pathlib import Path

import httpx
import pandas as pd
from loguru import logger

# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# ── Config ────────────────────────────────────────────────────────────────────

NOAA_BASE = "https://coast.noaa.gov/htdata/CMSP/AISDataHandler/2024"

# Sample days per month — spread across beginning, middle, and end of month
# to capture weekly traffic patterns without downloading all 30 days
SAMPLE_DAYS = {
    1:  [5, 15, 25],   # January
    2:  [5, 14, 24],   # February
    3:  [5, 15, 25],   # March
    4:  [5, 15, 25],   # April
    5:  [5, 15, 25],   # May
    6:  [5, 15, 25],   # June
    7:  [5, 15, 25],   # July
    8:  [5, 15, 25],   # August
    9:  [5, 15, 25],   # September
    10: [5, 15, 25],   # October
    11: [5, 15, 25],   # November
    12: [5, 15, 25],   # December
}

# Bounding boxes (min_lon, min_lat, max_lon, max_lat)
BBOXES = {
    "gulf_of_maine":      (-76.0, 40.0, -60.0, 50.0),
    "southeast_us":       (-82.0, 24.0, -76.0, 32.0),
    "santa_barbara":      (-122.0, 32.0, -117.0, 35.5),  # Blue/Humpback hotspot
    "gulf_farallones":    (-124.0, 36.5, -121.0, 38.5),  # Blue Whale feeding
    "san_pedro_channel":  (-120.5, 32.5, -117.0, 34.5),  # Humpback/Blue corridor
}

# Columns to keep
KEEP_COLS = ["MMSI", "VesselType", "SOG", "LAT", "LON", "BaseDateTime"]
RENAME    = {
    "MMSI":         "mmsi",
    "VesselType":   "vessel_type",
    "SOG":          "speed_knots",
    "LAT":          "lat",
    "LON":          "lon",
    "BaseDateTime": "timestamp",
}

OUT_DIR = REPO_ROOT / "data" / "raw" / "ais"


# ── Helpers ───────────────────────────────────────────────────────────────────

def in_bbox(df: pd.DataFrame) -> pd.DataFrame:
    """Keep rows within any of our bounding boxes."""
    mask = pd.Series(False, index=df.index)
    for min_lon, min_lat, max_lon, max_lat in BBOXES.values():
        mask |= (
            df["LON"].between(min_lon, max_lon) &
            df["LAT"].between(min_lat, max_lat)
        )
    return df[mask]


def clean(df: pd.DataFrame) -> pd.DataFrame:
    available = [c for c in KEEP_COLS if c in df.columns]
    df = df[available].rename(columns={k: v for k, v in RENAME.items() if k in df.columns})

    df["speed_knots"] = pd.to_numeric(df.get("speed_knots"), errors="coerce")
    df["lat"]         = pd.to_numeric(df.get("lat"),         errors="coerce")
    df["lon"]         = pd.to_numeric(df.get("lon"),         errors="coerce")
    df["timestamp"]   = pd.to_datetime(df.get("timestamp"),  errors="coerce")

    df = df.dropna(subset=["lat", "lon", "timestamp"])
    df = df[df["speed_knots"] > 0]
    return df.reset_index(drop=True)


def fetch_day(month: int, day: int, max_retries: int = 3) -> pd.DataFrame | None:
    """Download, unzip, clip, and clean one daily CSV. Streams in chunks with retries."""
    url = f"{NOAA_BASE}/AIS_2024_{month:02d}_{day:02d}.zip"
    logger.info(f"  Fetching {url.split('/')[-1]}...")

    for attempt in range(1, max_retries + 1):
        try:
            buf = io.BytesIO()
            with httpx.stream("GET", url, timeout=600, follow_redirects=True) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length", 0))
                downloaded = 0
                for chunk in r.iter_bytes(chunk_size=1024 * 1024):  # 1 MB chunks
                    buf.write(chunk)
                    downloaded += len(chunk)
            logger.info(f"    Downloaded {downloaded / 1e6:.1f} MB")
            break  # success
        except httpx.HTTPStatusError as e:
            logger.warning(f"    HTTP {e.response.status_code} — skipping")
            return None
        except Exception as e:
            if attempt < max_retries:
                logger.warning(f"    Attempt {attempt} failed: {e} — retrying...")
                buf = io.BytesIO()
            else:
                logger.warning(f"    All {max_retries} attempts failed: {e} — skipping")
                return None

    try:
        buf.seek(0)
        with zipfile.ZipFile(buf) as zf:
            csv_name = zf.namelist()[0]
            with zf.open(csv_name) as f:
                df = pd.read_csv(f, low_memory=False)
    except Exception as e:
        logger.warning(f"    Failed to parse zip: {e}")
        return None

    logger.info(f"    Raw rows: {len(df):,}")
    df = in_bbox(df)
    logger.info(f"    After bbox clip: {len(df):,}")
    df = clean(df)
    logger.info(f"    After cleaning: {len(df):,}")
    return df


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_month(month: int, days: list[int]) -> None:
    out_path = OUT_DIR / f"AIS_2024_{month:02d}_sampled.parquet"
    if out_path.exists():
        logger.info(f"Month {month:02d} already downloaded — skipping")
        return

    logger.info(f"── Month {month:02d} (sampling days {days}) ──")
    frames = []
    for day in days:
        df = fetch_day(month, day)
        if df is not None and not df.empty:
            df["sample_day"] = day
            frames.append(df)

    if not frames:
        logger.warning(f"No data retrieved for month {month:02d}")
        return

    combined = pd.concat(frames, ignore_index=True)
    combined.to_parquet(out_path, index=False)
    size_mb = out_path.stat().st_size / 1_000_000
    logger.success(f"  Saved {len(combined):,} rows → {out_path.name} ({size_mb:.1f} MB)")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Output: {OUT_DIR}")
    logger.info(f"Months: {list(SAMPLE_DAYS.keys())}, sampling {list(SAMPLE_DAYS.values())[0]} days each")

    for month, days in SAMPLE_DAYS.items():
        fetch_month(month, days)

    logger.success("NOAA AIS ingestion complete.")
    for f in sorted(OUT_DIR.glob("AIS_*.parquet")):
        df = pd.read_parquet(f)
        logger.info(f"  {f.name}: {len(df):,} rows")


if __name__ == "__main__":
    main()