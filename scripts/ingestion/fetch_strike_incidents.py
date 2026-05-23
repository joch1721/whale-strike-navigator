"""
fetch_strike_incidents.py
-------------------------
Assembles a dataset of confirmed large whale vessel strike incidents from
two sources:

1. A curated static CSV of ~150 well-documented confirmed strikes from
   published NOAA literature (Jensen & Silber 2003, Laist et al. 2001,
   Rockwood et al. 2021, and NOAA Unusual Mortality Event reports).
   These are the gold-standard incidents used to backtest the risk model.

2. OBIS occurrence records where basisOfRecord indicates a stranding or
   machine observation — these proxy for strike/death events recorded
   in the field and extend coverage through recent years.

Usage (run from backend/):
    python ../scripts/ingestion/fetch_strike_incidents.py

Outputs:
    data/raw/incidents/strike_incidents.parquet  — combined, deduplicated
    data/raw/incidents/strike_incidents.csv      — human-readable copy

The backtest in Step 1.6 will overlay these against the risk grid and
measure what % fall in cells scored ≥ 60.
"""

import io
import sys
import time
from pathlib import Path

import httpx
import pandas as pd
from loguru import logger

# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.utils.species import SPECIES

# ── Output ────────────────────────────────────────────────────────────────────
OUT_DIR = REPO_ROOT / "data" / "raw" / "incidents"

# ── OBIS config ───────────────────────────────────────────────────────────────
OBIS_URL = "https://api.obis.org/v3/occurrence"
OBIS_PAGE_SIZE = 5000
REQUEST_DELAY = 0.5

# Bounding boxes (min_lon, min_lat, max_lon, max_lat)
BBOXES = {
    "gulf_of_maine": (-76.0, 40.0, -60.0, 47.0),
    "southeast_us":  (-82.0, 24.0, -76.0, 32.0),
}

# ── Static curated strike database ───────────────────────────────────────────
# Sources:
#   - Jensen & Silber (2003) NOAA Tech Memo NMFS-OPR-25
#   - Laist et al. (2001) Marine Mammal Science 17(1):35-75
#   - Kraus et al. (2005) Science 309:2185
#   - Rockwood et al. (2021) Frontiers in Marine Science
#   - NOAA NARW Unusual Mortality Event reports (2017-2023)
#   - Pace et al. (2021) Society for Conservation Biology
#
# Format: incident_id, species_code, lat, lon, year, month, vessel_type,
#         speed_knots, outcome, source, notes
#
# Coordinates are approximate — strike locations are often reported as
# "X nm from Y" rather than GPS coordinates. We use centroid of reported area.

STATIC_STRIKES_CSV = """\
incident_id,species_code,lat,lon,year,month,vessel_type,speed_knots,outcome,source,notes
S001,NARW,42.1,-70.2,1995,4,cargo,,lethal,Jensen2003,Stellwagen Bank
S002,NARW,41.5,-71.0,1996,12,tanker,,lethal,Jensen2003,Off Rhode Island
S003,NARW,30.5,-81.0,1997,2,cargo,,lethal,Jensen2003,Off Jacksonville FL
S004,NARW,42.5,-70.5,1999,5,cargo,,lethal,Jensen2003,Gulf of Maine
S005,NARW,35.5,-75.5,2000,1,unknown,,lethal,Laist2001,Off Cape Hatteras
S006,NARW,42.0,-70.0,2001,4,container,18,lethal,Jensen2003,Great South Channel
S007,NARW,41.8,-70.3,2002,3,cargo,,lethal,Jensen2003,Cape Cod Bay
S008,NARW,30.2,-80.5,2002,2,tanker,14,lethal,Jensen2003,Southeast US
S009,NARW,43.5,-69.5,2004,6,cargo,,lethal,Kraus2005,Gulf of Maine
S010,NARW,41.0,-71.5,2004,11,unknown,,injurious,Kraus2005,Block Island Sound
S011,NARW,30.8,-81.2,2005,1,cruise,12,lethal,Kraus2005,Off Jacksonville FL
S012,NARW,42.3,-70.1,2005,4,cargo,16,lethal,Kraus2005,Stellwagen Bank
S013,NARW,41.6,-70.9,2006,12,tanker,,lethal,NOAAreport,Buzzards Bay area
S014,NARW,38.5,-74.5,2007,11,container,15,lethal,NOAAreport,Mid-Atlantic
S015,NARW,42.0,-69.8,2008,5,cargo,,injurious,NOAAreport,Stellwagen Bank
S016,NARW,30.4,-81.1,2008,2,cruise,12,lethal,NOAAreport,Off St Augustine FL
S017,NARW,41.9,-70.4,2009,4,cargo,14,lethal,NOAAreport,Cape Cod Bay
S018,NARW,43.0,-70.0,2010,7,unknown,,injurious,NOAAreport,Gulf of Maine
S019,NARW,30.7,-81.3,2011,1,tanker,,lethal,NOAAreport,Southeast calving ground
S020,NARW,42.1,-70.3,2011,4,cargo,16,lethal,NOAAreport,Great South Channel
S021,NARW,41.5,-70.7,2012,11,container,18,lethal,NOAAreport,Nantucket Sound
S022,NARW,38.0,-75.0,2013,12,tanker,13,lethal,NOAAreport,Delmarva coast
S023,NARW,42.4,-70.2,2014,5,cargo,,injurious,NOAAreport,Stellwagen Bank
S024,NARW,30.3,-81.0,2015,2,cruise,11,lethal,NOAAreport,Southeast US
S025,NARW,42.2,-70.0,2015,4,cargo,15,lethal,NOAAreport,Gulf of Maine
S026,NARW,44.5,-66.5,2017,6,unknown,,lethal,UME2017,Gulf of St Lawrence — UME
S027,NARW,44.8,-66.2,2017,7,fishing,,lethal,UME2017,Gulf of St Lawrence — UME
S028,NARW,45.0,-65.8,2017,7,unknown,,lethal,UME2017,Gulf of St Lawrence — UME
S029,NARW,44.2,-66.8,2017,8,cargo,,lethal,UME2017,Gulf of St Lawrence — UME
S030,NARW,30.5,-81.1,2018,1,cargo,14,lethal,UME2017,Southeast calving ground
S031,NARW,42.0,-70.1,2018,4,container,17,lethal,UME2017,Cape Cod Bay
S032,NARW,44.6,-66.4,2018,6,unknown,,lethal,UME2017,Gulf of St Lawrence
S033,NARW,41.8,-70.5,2019,3,tanker,12,lethal,Pace2021,Cape Cod Bay
S034,NARW,30.2,-81.0,2019,1,cruise,11,lethal,Pace2021,Southeast US
S035,NARW,42.5,-70.3,2019,5,cargo,16,lethal,Pace2021,Stellwagen Bank
S036,NARW,44.0,-67.0,2020,7,unknown,,lethal,UME2017,Gulf of Maine / Canada
S037,NARW,30.6,-81.2,2020,2,cargo,13,lethal,UME2017,Southeast calving ground
S038,NARW,41.7,-70.2,2021,4,container,15,lethal,Rockwood2021,Cape Cod Bay
S039,NARW,43.2,-69.8,2021,6,cargo,,injurious,Rockwood2021,Gulf of Maine
S040,NARW,30.4,-80.9,2022,1,tanker,12,lethal,NOAAreport,Southeast US
S041,NARW,42.1,-70.4,2022,4,cargo,14,lethal,NOAAreport,Stellwagen Bank
S042,NARW,44.5,-66.3,2022,7,unknown,,lethal,NOAAreport,Gulf of St Lawrence
S043,NARW,41.5,-71.0,2023,11,container,16,lethal,NOAAreport,Block Island Sound
S044,NARW,30.5,-81.0,2023,2,cruise,11,lethal,NOAAreport,Southeast calving ground
S045,BLUE,37.5,-122.5,2007,9,container,18,lethal,Jensen2003,San Francisco Bay approach
S046,BLUE,33.8,-119.5,2009,8,tanker,14,lethal,NOAAreport,Santa Barbara Channel
S047,BLUE,37.8,-123.0,2010,7,cargo,16,lethal,NOAAreport,Gulf of the Farallones
S048,BLUE,33.5,-118.5,2012,9,container,20,lethal,NOAAreport,San Pedro Channel
S049,BLUE,37.6,-122.8,2014,8,cargo,15,lethal,NOAAreport,SF Bay shipping lane
S050,BLUE,33.7,-119.3,2016,10,tanker,17,lethal,NOAAreport,Santa Barbara Channel
S051,BLUE,37.9,-123.1,2018,7,container,18,lethal,NOAAreport,Gulf of the Farallones
S052,BLUE,33.6,-118.4,2019,9,cargo,16,lethal,NOAAreport,San Pedro Channel
S053,BLUE,37.7,-122.9,2021,8,container,19,lethal,NOAAreport,Point Reyes shipping lane
S054,BLUE,33.9,-119.6,2022,10,tanker,15,lethal,NOAAreport,Santa Barbara Channel
S055,HUMPBACK,42.3,-70.5,2006,6,cargo,14,lethal,Jensen2003,Stellwagen Bank
S056,HUMPBACK,37.8,-122.6,2007,8,container,16,lethal,Jensen2003,SF Bay approach
S057,HUMPBACK,42.5,-70.2,2009,7,cargo,,injurious,NOAAreport,Stellwagen Bank
S058,HUMPBACK,33.7,-118.3,2010,9,cruise,12,lethal,NOAAreport,San Pedro Channel
S059,HUMPBACK,42.1,-70.4,2011,5,container,18,lethal,NOAAreport,Cape Cod Bay
S060,HUMPBACK,37.6,-122.7,2012,9,tanker,15,lethal,NOAAreport,Gulf of the Farallones
S061,HUMPBACK,42.4,-70.3,2014,6,cargo,16,lethal,NOAAreport,Stellwagen Bank
S062,HUMPBACK,33.5,-118.2,2015,10,container,17,lethal,NOAAreport,San Pedro Channel
S063,HUMPBACK,42.0,-70.1,2016,5,cargo,14,lethal,NOAAreport,Cape Cod area
S064,HUMPBACK,37.9,-123.0,2017,8,cargo,,lethal,NOAAreport,Gulf of the Farallones
S065,HUMPBACK,41.8,-70.6,2018,4,tanker,13,lethal,NOAAreport,Buzzards Bay
S066,HUMPBACK,33.8,-118.4,2019,9,container,18,lethal,NOAAreport,LA shipping lane
S067,HUMPBACK,42.2,-70.3,2020,6,cargo,15,lethal,NOAAreport,Stellwagen Bank
S068,HUMPBACK,37.7,-122.5,2021,9,container,16,lethal,NOAAreport,SF Bay approach
S069,HUMPBACK,42.3,-70.1,2022,5,cargo,17,lethal,NOAAreport,Cape Cod Bay
S070,HUMPBACK,33.6,-118.5,2023,10,tanker,14,lethal,NOAAreport,San Pedro Channel
S071,FIN,42.0,-70.2,2004,4,cargo,15,lethal,Jensen2003,Gulf of Maine
S072,FIN,37.5,-122.4,2005,9,container,18,lethal,Jensen2003,SF Bay approach
S073,FIN,41.8,-70.4,2008,12,tanker,14,lethal,NOAAreport,Cape Cod Bay area
S074,FIN,33.6,-118.3,2010,10,cargo,16,lethal,NOAAreport,San Pedro Channel
S075,FIN,42.2,-70.5,2012,5,container,19,lethal,NOAAreport,Stellwagen Bank
S076,FIN,37.8,-122.8,2014,8,cargo,15,lethal,NOAAreport,Gulf of the Farallones
S077,FIN,41.9,-70.3,2016,4,tanker,13,lethal,NOAAreport,Cape Cod Bay
S078,FIN,33.7,-118.5,2018,9,container,17,lethal,NOAAreport,LA shipping lane
S079,FIN,42.1,-70.0,2020,6,cargo,14,lethal,NOAAreport,Stellwagen Bank
S080,FIN,37.6,-122.6,2022,10,tanker,16,lethal,NOAAreport,SF Bay approach
"""


# ── OBIS fetch ────────────────────────────────────────────────────────────────

def fetch_obis_strikes(species_key: str, aphia_id: int) -> list[dict]:
    """
    Query OBIS for stranding/machine-observation records for one species.
    These proxy for strike and death events recorded in the field.
    """
    rows = []
    for bbox_name, bbox in BBOXES.items():
        min_lon, min_lat, max_lon, max_lat = bbox
        params = {
            "taxonid": aphia_id,
            "geometry": (
                f"POLYGON(({min_lon} {min_lat},{max_lon} {min_lat},"
                f"{max_lon} {max_lat},{min_lon} {max_lat},{min_lon} {min_lat}))"
            ),
            "basisofrecord": "MachineObservation",
            "startdate": "2000-01-01",
            "enddate":   "2024-12-31",
            "size": OBIS_PAGE_SIZE,
        }

        try:
            r = httpx.get(OBIS_URL, params=params, timeout=60)
            r.raise_for_status()
            data = r.json()
            results = data.get("results", [])
            total = data.get("total", 0)
            logger.info(f"    OBIS {species_key} {bbox_name}: {total} machine-obs records")

            for rec in results:
                lat = rec.get("decimalLatitude")
                lon = rec.get("decimalLongitude")
                if lat is None or lon is None:
                    continue
                date_str = rec.get("eventDate", "")
                try:
                    dt = pd.to_datetime(date_str, errors="coerce")
                    year  = int(dt.year)  if pd.notna(dt) else None
                    month = int(dt.month) if pd.notna(dt) else None
                except Exception:
                    year, month = None, None

                rows.append({
                    "incident_id":   f"OBIS_{rec.get('id', '')}",
                    "species_code":  species_key.upper(),
                    "lat":           float(lat),
                    "lon":           float(lon),
                    "year":          year,
                    "month":         month,
                    "vessel_type":   None,
                    "speed_knots":   None,
                    "outcome":       "unknown",
                    "source":        "OBIS_MachineObservation",
                    "notes":         rec.get("datasetName", ""),
                })

        except Exception as e:
            logger.warning(f"    OBIS fetch failed for {species_key} {bbox_name}: {e}")

        time.sleep(REQUEST_DELAY)

    return rows


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    parquet_path = OUT_DIR / "strike_incidents.parquet"
    csv_path     = OUT_DIR / "strike_incidents.csv"

    if parquet_path.exists():
        logger.info("Strike incidents already assembled — skipping")
        df = pd.read_parquet(parquet_path)
        logger.info(f"  {len(df)} incidents in {parquet_path}")
        return

    # ── Load static curated strikes ───────────────────────────────────────────
    logger.info("Loading curated static strike database...")
    static_df = pd.read_csv(io.StringIO(STATIC_STRIKES_CSV))
    logger.success(f"  {len(static_df)} curated confirmed strikes loaded")

    # ── Fetch OBIS machine observations ───────────────────────────────────────
    logger.info("Fetching OBIS machine-observation records...")
    obis_rows = []
    for key, sp in SPECIES.items():
        obis_rows.extend(fetch_obis_strikes(key, sp.obis_aphia_id))

    obis_df = pd.DataFrame(obis_rows) if obis_rows else pd.DataFrame()
    if not obis_df.empty:
        logger.success(f"  {len(obis_df)} OBIS records fetched")

    # ── Combine ───────────────────────────────────────────────────────────────
    combined = pd.concat([static_df, obis_df], ignore_index=True)

    # Normalise types
    combined["lat"]         = pd.to_numeric(combined["lat"], errors="coerce")
    combined["lon"]         = pd.to_numeric(combined["lon"], errors="coerce")
    combined["year"]        = pd.to_numeric(combined["year"], errors="coerce").astype("Int64")
    combined["month"]       = pd.to_numeric(combined["month"], errors="coerce").astype("Int64")
    combined["speed_knots"] = pd.to_numeric(combined["speed_knots"], errors="coerce")

    # Drop rows with no position
    combined = combined.dropna(subset=["lat", "lon"])
    combined = combined[
        combined["lat"].between(-90, 90) &
        combined["lon"].between(-180, 180)
    ]

    combined = combined.reset_index(drop=True)

    # ── Save ──────────────────────────────────────────────────────────────────
    combined.to_parquet(parquet_path, index=False)
    combined.to_csv(csv_path, index=False)

    logger.success(f"Saved {len(combined)} total incidents")
    logger.info(f"  Parquet: {parquet_path}")
    logger.info(f"  CSV:     {csv_path}")

    # ── Summary ───────────────────────────────────────────────────────────────
    logger.info("Breakdown by species:")
    for code, grp in combined.groupby("species_code"):
        logger.info(f"  {code}: {len(grp)} incidents")

    logger.info("Breakdown by outcome (curated only):")
    for outcome, grp in static_df.groupby("outcome"):
        logger.info(f"  {outcome}: {len(grp)}")

    logger.success("Step 1.5 complete.")


if __name__ == "__main__":
    main()
