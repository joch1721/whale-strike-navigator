"""
routers/vessels.py
------------------
GET /vessels/live — fetches a snapshot of live AIS vessel positions
by opening a short-lived WebSocket to aisstream.io, collecting
messages for ~10 seconds, then returning the result.

No persistent collector needed — works on single-process Render free tier.
"""

import asyncio
import json
import ssl
import certifi
from datetime import datetime, timezone
from pathlib import Path

import websockets
from fastapi import APIRouter
from loguru import logger

from app.config import settings

router = APIRouter()

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"

BOUNDING_BOXES = [
    [[40.0, -76.0], [47.0, -60.0]],
    [[24.0, -82.0], [32.0, -76.0]],
]

COLLECT_SECONDS = 10
MAX_VESSELS     = 300


def speed_tier(knots) -> str:
    try:
        k = float(knots)
        if k > 14:  return "fast"
        if k > 10:  return "medium"
        if k > 0:   return "slow"
    except (TypeError, ValueError):
        pass
    return "unknown"


async def collect_live_vessels() -> list[dict]:
    """Open a WebSocket, collect position reports for COLLECT_SECONDS, return list."""
    if not settings.aisstream_api_key:
        return []

    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    subscribe = {
        "APIKey":             settings.aisstream_api_key,
        "BoundingBoxes":      BOUNDING_BOXES,
        "FilterMessageTypes": ["PositionReport"],
    }

    vessels: dict[str, dict] = {}  # mmsi → latest position

    try:
        async with websockets.connect(
            AISSTREAM_URL,
            ssl=ssl_ctx,
            open_timeout=10,
            ping_interval=None,
        ) as ws:
            await ws.send(json.dumps(subscribe))

            deadline = asyncio.get_event_loop().time() + COLLECT_SECONDS
            while asyncio.get_event_loop().time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    msg = json.loads(raw)
                except asyncio.TimeoutError:
                    continue
                except Exception:
                    break

                if msg.get("MessageType") != "PositionReport":
                    continue

                meta   = msg.get("MetaData", {})
                report = msg.get("Message", {}).get("PositionReport", {})
                lat    = report.get("Latitude")
                lon    = report.get("Longitude")
                mmsi   = str(meta.get("MMSI", ""))

                if lat is None or lon is None or not mmsi:
                    continue
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    continue

                speed = report.get("SpeedOverGround")
                vessels[mmsi] = {
                    "mmsi":         mmsi,
                    "vessel_name":  meta.get("ShipName", "").strip() or "Unknown",
                    "lat":          float(lat),
                    "lon":          float(lon),
                    "speed_knots":  float(speed) if speed is not None else None,
                    "heading":      report.get("TrueHeading"),
                    "speed_tier":   speed_tier(speed),
                    "source":       "aisstream.io",
                }

                if len(vessels) >= MAX_VESSELS:
                    break

    except Exception as e:
        logger.warning(f"Live vessel collection failed: {e}")

    return list(vessels.values())


@router.get("/live")
async def get_live_vessels():
    """
    Fetch a live snapshot of vessel positions by connecting to aisstream.io
    for ~10 seconds. Results reflect vessels active right now in the
    NARW habitat bounding boxes.
    """
    vessels = await collect_live_vessels()

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [v["lon"], v["lat"]]},
            "properties": v,
        }
        for v in vessels
    ]

    return {
        "type":         "FeatureCollection",
        "features":     features,
        "vessel_count": len(vessels),
        "source":       "aisstream.io",
        "status":       "ok" if vessels else "no_data",
        "fetched_at":   datetime.now(timezone.utc).isoformat(),
    }