"""
Pydantic models for vessel and AIS data structures.
"""

from typing import Optional
from pydantic import BaseModel, Field


# AIS vessel type codes → human-readable + risk weight
# Weights reflect strike risk: large, fast, deep-drafted vessels score higher
VESSEL_TYPE_WEIGHTS: dict[int, tuple[str, float]] = {
    # Tankers
    80: ("Tanker", 1.0),
    81: ("Tanker", 1.0),
    82: ("Tanker", 1.0),
    83: ("Tanker", 1.0),
    84: ("Tanker", 1.0),
    # Cargo
    70: ("Cargo", 0.9),
    71: ("Cargo", 0.9),
    72: ("Cargo", 0.9),
    79: ("Cargo", 0.9),
    # Container (often fastest commercial vessels)
    # AIS type 70–79 covers cargo; container ships typically self-report as 70
    # Passenger / cruise
    60: ("Passenger", 0.8),
    61: ("Passenger", 0.8),
    69: ("Passenger", 0.8),
    # High speed craft
    40: ("High Speed Craft", 0.95),
    # Fishing
    30: ("Fishing", 0.4),
    # Tug
    52: ("Tug", 0.3),
    # Pleasure craft / sailing
    36: ("Sailing", 0.1),
    37: ("Pleasure Craft", 0.1),
    # Other / unknown
    0: ("Unknown", 0.5),
}


def get_vessel_type_info(type_code: int) -> tuple[str, float]:
    """Return (label, risk_weight) for an AIS vessel type code."""
    # Try exact match, then fall back to decade bucket (e.g. 72 → 70)
    if type_code in VESSEL_TYPE_WEIGHTS:
        return VESSEL_TYPE_WEIGHTS[type_code]
    bucket = (type_code // 10) * 10
    return VESSEL_TYPE_WEIGHTS.get(bucket, ("Unknown", 0.5))


class VesselPosition(BaseModel):
    """A single AIS vessel position report."""

    mmsi: str = Field(..., description="Maritime Mobile Service Identity")
    name: Optional[str] = None
    vessel_type_code: int = Field(0, description="AIS vessel type code")
    vessel_type_label: str = Field("Unknown")
    vessel_type_weight: float = Field(0.5, ge=0.0, le=1.0)

    lat: float
    lon: float
    speed_knots: float = Field(0.0, ge=0.0)
    heading: Optional[float] = Field(None, ge=0.0, lt=360.0)
    timestamp: str  # ISO 8601


class LiveVesselsResponse(BaseModel):
    """API response for live vessel positions."""

    vessel_count: int
    fetched_at: str
    source: str = "AISHub"
    vessels: list[VesselPosition]
