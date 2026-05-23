"""
routers/vessels.py
------------------
GET /vessels/live — returns today's live AIS vessel positions as GeoJSON.

Reads the most recent live_YYYY-MM-DD.parquet file written by
stream_aisstream.py and returns vessel positions for the map layer.
"""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from loguru import logger

router = APIRouter()

# Path to live AIS data
REPO_ROOT = Path(__file__).resolve().parents[4]
AIS_DIR   = REPO_ROOT / "data" / "raw" / "ais"

# Speed thresholds for colour coding
def speed_tier(knots) -> str:
    try:
        k = float(knots)
        if k > 14:   return "fast"
        if k > 10:   return "medium"
        if k > 0:    return "slow"
    except (TypeError, ValueError):
        pass
    return "unknown"


@router.get("/live")
async def get_live_vessels():
    """
    Return live vessel positions from today's aisstream collector file.
    Falls back to most recent available file if today's isn't present.
    """
    import pandas as pd

    # Find most recent live file
    live_files = sorted(AIS_DIR.glob("live_*.parquet"), reverse=True)
    if not live_files:
        return {
            "type": "FeatureCollection",
            "features": [],
            "vessel_count": 0,
            "source": "aisstream.io",
            "status": "no_data",
            "message": "No live data yet — run stream_aisstream.py to collect",
        }

    latest = live_files[0]
    df = pd.read_parquet(latest)

    # Drop rows with no position
    df = df.dropna(subset=["lat", "lon"])
    df = df[df["lat"].between(-90, 90) & df["lon"].between(-180, 180)]

    features = []
    for _, row in df.iterrows():
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(row["lon"]), float(row["lat"])],
            },
            "properties": {
                "mmsi":         str(row.get("mmsi", "")),
                "vessel_name":  str(row.get("vessel_name", "Unknown")).strip() or "Unknown",
                "speed_knots":  float(row["speed_knots"]) if row.get("speed_knots") is not None and str(row.get("speed_knots")) != "None" else None,
                "heading":      float(row["heading"]) if row.get("heading") is not None and str(row.get("heading")) not in ("None", "511") else None,
                "nav_status":   int(row["nav_status"]) if row.get("nav_status") is not None else None,
                "speed_tier":   speed_tier(row.get("speed_knots")),
                "source":       "aisstream.io",
            },
        })

    file_date = latest.stem.replace("live_", "")

    return {
        "type":         "FeatureCollection",
        "features":     features,
        "vessel_count": len(features),
        "source":       "aisstream.io",
        "status":       "ok",
        "data_date":    file_date,
        "fetched_at":   datetime.now(timezone.utc).isoformat(),
    }
