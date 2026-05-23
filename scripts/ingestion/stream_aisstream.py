"""
stream_aisstream.py
-------------------
Connects to aisstream.io via WebSocket and collects live AIS position reports
for vessels in NARW habitat bounding boxes.

Buffers messages in memory and flushes to a rolling Parquet file every
FLUSH_INTERVAL_SECONDS seconds. Each flush appends to the current day's file.

Usage (run from repo root):
    python -m scripts.ingestion.stream_aisstream

    # Run for a fixed duration (seconds), useful for testing:
    python -m scripts.ingestion.stream_aisstream --duration 60

Outputs:
    data/raw/ais/live_YYYY-MM-DD.parquet  (one file per UTC day, appended)

Requires:
    AISSTREAM_API_KEY in backend/.env  (or set as environment variable)
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import ssl

import certifi
import pandas as pd
import ssl
import websockets
from loguru import logger

# ── Path setup ────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# Load .env manually so this script works standalone outside uvicorn
from dotenv import load_dotenv
load_dotenv(REPO_ROOT / "backend" / ".env")

# ── Config ────────────────────────────────────────────────────────────────────

AISSTREAM_URL = "wss://stream.aisstream.io/v0/stream"
API_KEY = os.getenv("AISSTREAM_API_KEY", "")

# Bounding boxes: [[min_lat, min_lon], [max_lat, max_lon]]
# aisstream uses [lat, lon] order (opposite of GeoJSON!)
BOUNDING_BOXES = [
    # Gulf of Maine + Mid-Atlantic (primary NARW feeding grounds)
    [[40.0, -76.0], [47.0, -60.0]],
    # Southeast US (NARW winter calving grounds)
    [[24.0, -82.0], [32.0, -76.0]],
]

# Only pull position reports — we don't need voyage or static data yet
FILTER_MESSAGE_TYPES = ["PositionReport"]

# Vessel types to keep (AIS numeric codes)
# 70–79 = Cargo, 80–89 = Tanker, 60–69 = Passenger, 40–49 = High Speed
# 0 = Unknown (keep — many vessels report 0)
KEEP_VESSEL_TYPES = set(range(0, 1)) | set(range(40, 50)) | set(range(60, 90))

# How often to flush the buffer to disk (seconds)
FLUSH_INTERVAL_SECONDS = 300  # 5 minutes

# Output directory
OUT_DIR = REPO_ROOT / "data" / "raw" / "ais"


# ── Buffer ────────────────────────────────────────────────────────────────────

class MessageBuffer:
    """Thread-safe in-memory buffer for AIS messages."""

    def __init__(self):
        self._rows: list[dict] = []

    def add(self, row: dict) -> None:
        self._rows.append(row)

    def flush(self) -> list[dict]:
        rows, self._rows = self._rows, []
        return rows

    def __len__(self) -> int:
        return len(self._rows)


# ── Parsing ───────────────────────────────────────────────────────────────────

def parse_position_report(message: dict) -> dict | None:
    """
    Extract fields we need from an aisstream PositionReport message.
    Returns None if the message is malformed or missing required fields.

    aisstream message shape:
    {
        "MessageType": "PositionReport",
        "MetaData": { "MMSI": ..., "ShipName": ..., "time_utc": ..., ... },
        "Message": {
            "PositionReport": {
                "Latitude": ..., "Longitude": ...,
                "SpeedOverGround": ..., "TrueHeading": ...,
                "NavigationalStatus": ..., ...
            }
        }
    }
    """
    try:
        meta = message.get("MetaData", {})
        report = message.get("Message", {}).get("PositionReport", {})

        lat = report.get("Latitude")
        lon = report.get("Longitude")
        speed = report.get("SpeedOverGround")
        mmsi = meta.get("MMSI")
        timestamp = meta.get("time_utc") or datetime.now(timezone.utc).isoformat()

        # Basic validation
        if lat is None or lon is None or mmsi is None:
            return None
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return None

        return {
            "mmsi": str(mmsi),
            "vessel_name": meta.get("ShipName", "").strip() or None,
            "lat": float(lat),
            "lon": float(lon),
            "speed_knots": float(speed) if speed is not None else None,
            "heading": report.get("TrueHeading"),
            "nav_status": report.get("NavigationalStatus"),
            "timestamp": timestamp,
            "source": "aisstream",
        }
    except Exception as e:
        logger.debug(f"Failed to parse message: {e}")
        return None


# ── Flush ─────────────────────────────────────────────────────────────────────

def flush_to_parquet(buffer: MessageBuffer) -> None:
    """Write buffered rows to today's rolling Parquet file."""
    rows = buffer.flush()
    if not rows:
        logger.debug("Buffer empty — nothing to flush")
        return

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_path = OUT_DIR / f"live_{today}.parquet"

    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)

    if out_path.exists():
        existing = pd.read_parquet(out_path)
        df = pd.concat([existing, df], ignore_index=True)
        # Deduplicate on mmsi + timestamp
        df = df.drop_duplicates(subset=["mmsi", "timestamp"])

    df.to_parquet(out_path, index=False)
    logger.info(f"Flushed {len(rows):,} messages → {out_path.name} ({len(df):,} total rows)")


# ── WebSocket loop ────────────────────────────────────────────────────────────

async def stream(buffer: MessageBuffer, stop_event: asyncio.Event) -> None:
    """Main WebSocket loop — reconnects automatically on disconnect."""

    if not API_KEY:
        logger.error("AISSTREAM_API_KEY is not set. Add it to backend/.env")
        stop_event.set()
        return

    subscribe_msg = {
        "APIKey": API_KEY,
        "BoundingBoxes": BOUNDING_BOXES,
        "FilterMessageTypes": FILTER_MESSAGE_TYPES,
    }

    backoff = 1  # seconds before reconnect attempt

    while not stop_event.is_set():
        try:
            logger.info(f"Connecting to {AISSTREAM_URL}...")
            ssl_ctx = ssl.create_default_context(cafile=certifi.where())
            async with websockets.connect(
                AISSTREAM_URL,
                ssl=ssl_ctx,
                ping_interval=20,
                ping_timeout=30,
                open_timeout=15,
            ) as ws:
                await ws.send(json.dumps(subscribe_msg))
                logger.success("Connected — streaming AIS position reports")
                backoff = 1  # reset on successful connect

                async for raw in ws:
                    if stop_event.is_set():
                        break
                    try:
                        message = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if message.get("MessageType") != "PositionReport":
                        continue

                    row = parse_position_report(message)
                    if row:
                        buffer.add(row)

        except websockets.exceptions.ConnectionClosedError as e:
            logger.warning(f"Connection closed: {e} — reconnecting in {backoff}s")
        except OSError as e:
            logger.warning(f"Network error: {e} — reconnecting in {backoff}s")
        except Exception as e:
            logger.error(f"Unexpected error: {e} — reconnecting in {backoff}s")

        if not stop_event.is_set():
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)  # exponential backoff, cap at 60s


async def flusher(buffer: MessageBuffer, stop_event: asyncio.Event) -> None:
    """Periodically flushes the buffer to disk."""
    while not stop_event.is_set():
        await asyncio.sleep(FLUSH_INTERVAL_SECONDS)
        flush_to_parquet(buffer)


# ── Entry point ───────────────────────────────────────────────────────────────

async def run(duration: int | None = None) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    buffer = MessageBuffer()
    stop_event = asyncio.Event()

    logger.info("Starting aisstream.io collector")
    logger.info(f"Flush interval: {FLUSH_INTERVAL_SECONDS}s")
    logger.info(f"Output: {OUT_DIR}")
    if duration:
        logger.info(f"Running for {duration}s then stopping")

    tasks = [
        asyncio.create_task(stream(buffer, stop_event)),
        asyncio.create_task(flusher(buffer, stop_event)),
    ]

    try:
        if duration:
            await asyncio.sleep(duration)
            stop_event.set()
        else:
            # Run until Ctrl+C
            await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    except KeyboardInterrupt:
        logger.info("Interrupted — flushing buffer before exit...")
    finally:
        stop_event.set()
        flush_to_parquet(buffer)
        for task in tasks:
            task.cancel()
        logger.info(f"Collector stopped. {len(buffer)} messages discarded.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stream live AIS data from aisstream.io")
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Stop after N seconds (omit to run indefinitely)",
    )
    args = parser.parse_args()
    asyncio.run(run(duration=args.duration))


if __name__ == "__main__":
    main()