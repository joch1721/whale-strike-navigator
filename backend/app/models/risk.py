"""
Pydantic models for risk grid data structures.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


class GridCell(BaseModel):
    """A single 0.1° × 0.1° ocean grid cell with risk scores."""

    cell_id: str = Field(..., description="Unique cell identifier: 'lat_lon' at cell center")
    lat: float = Field(..., description="Cell center latitude")
    lon: float = Field(..., description="Cell center longitude")
    month: int = Field(..., ge=1, le=12, description="Month (1=Jan, 12=Dec)")

    # Input components
    shipping_density: float = Field(0.0, ge=0.0, le=1.0, description="Normalized vessel density")
    mean_vessel_speed: float = Field(0.0, ge=0.0, description="Mean vessel speed (knots)")
    vessel_type_weight: float = Field(0.0, ge=0.0, le=1.0, description="Weighted by vessel type risk")
    whale_presence_prob: float = Field(0.0, ge=0.0, le=1.0, description="Whale presence probability 0–1")

    # Output
    risk_score: float = Field(0.0, ge=0.0, le=100.0, description="Composite risk score 0–100")
    risk_tier: str = Field("low", description="low / medium / high / critical")

    species_present: List[str] = Field(
        default_factory=list,
        description="Species contributing to whale_presence_prob",
    )


class RiskGridResponse(BaseModel):
    """API response for a monthly risk grid query."""

    month: int
    species_filter: Optional[str] = None
    cell_count: int
    cells: List[GridCell]
    generated_at: str  # ISO timestamp


def risk_tier_from_score(score: float) -> str:
    """Map a 0–100 risk score to a named tier."""
    if score >= 75:
        return "critical"
    elif score >= 50:
        return "high"
    elif score >= 25:
        return "medium"
    else:
        return "low"
