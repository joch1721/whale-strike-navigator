"""
routers/incidents.py
--------------------
GET /incidents  — historical NOAA ship strike incidents
"""

import math
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from app.services.data_loader import get_incidents, is_data_loaded
from app.utils.cache import cached

router = APIRouter()


@router.get("")
@cached(ttl=3600)
async def list_incidents(
    species: Optional[str] = Query(None),
    month: Optional[int]   = Query(None, ge=1, le=12),
    min_year: Optional[int] = Query(None, ge=1970),
    outcome: Optional[str] = Query(None),
):
    """Return historical confirmed ship strike incidents. Cached 1 hour."""
    if not is_data_loaded():
        raise HTTPException(status_code=503, detail="Data not yet loaded")

    df = get_incidents(species=species, month=month, min_year=min_year)

    if outcome:
        df = df[df["outcome"] == outcome.lower()]

    records = [
        {k: (None if isinstance(v, float) and math.isnan(v) else v)
         for k, v in row.items()}
        for row in df.to_dict(orient="records")
    ]

    return {
        "incident_count": len(records),
        "filters": {"species": species, "month": month,
                    "min_year": min_year, "outcome": outcome},
        "generated_at": datetime.utcnow().isoformat(),
        "incidents": records,
    }
