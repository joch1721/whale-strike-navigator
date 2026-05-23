"""
routers/risk.py
---------------
GET /risk         — monthly risk grid cells
GET /risk/summary — tier counts and top cells per month
"""

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from loguru import logger

from app.services.data_loader import get_risk_grid, is_data_loaded
from app.utils.cache import cached

router = APIRouter()


@router.get("")
@cached(ttl=300)
async def get_risk(
    month: Optional[int] = Query(None, ge=1, le=12),
    species: Optional[str] = Query(None),
    min_score: float = Query(0.0, ge=0, le=100),
    tier: Optional[str] = Query(None),
    limit: int = Query(10000, ge=1, le=50000),
):
    """
    Return ocean grid cells with risk scores.
    Cached for 5 minutes — cache invalidates automatically on data reload.
    """
    if not is_data_loaded():
        raise HTTPException(status_code=503, detail="Data not yet loaded")

    df = get_risk_grid(month=month, species=species, min_score=min_score)

    if tier:
        df = df[df["risk_tier"] == tier.lower()]

    df = df.sort_values("risk_score", ascending=False).head(limit)
    cells = df.to_dict(orient="records")

    return {
        "month": month,
        "species_filter": species,
        "min_score": min_score,
        "tier_filter": tier,
        "cell_count": len(cells),
        "generated_at": datetime.utcnow().isoformat(),
        "cells": cells,
    }


@router.get("/summary")
@cached(ttl=600)
async def get_risk_summary():
    """
    Return tier counts and top cells per month.
    Cached for 10 minutes.
    """
    if not is_data_loaded():
        raise HTTPException(status_code=503, detail="Data not yet loaded")

    df = get_risk_grid()
    if df.empty:
        return {"months": []}

    summary = []
    for month in sorted(df["month"].unique()):
        month_df = df[df["month"] == month]
        tier_counts = month_df["risk_tier"].value_counts().to_dict()
        top_cells = (
            month_df[month_df["risk_score"] > 0]
            .sort_values("risk_score", ascending=False)
            .head(5)[["cell_id", "lat", "lon", "risk_score",
                       "risk_tier", "species_present"]]
            .to_dict(orient="records")
        )
        summary.append({
            "month": int(month),
            "total_cells": len(month_df),
            "tier_counts": tier_counts,
            "max_score": float(month_df["risk_score"].max()),
            "top_cells": top_cells,
        })

    return {"months": summary}


@router.get("/live")
async def get_live_risk():
    """
    Return the most recent live risk grid computed from today's
    aisstream.io vessel positions. Refreshes every 15 minutes.
    """
    import pandas as pd
    from pathlib import Path

    REPO_ROOT  = Path(__file__).resolve().parents[3]
    live_path  = REPO_ROOT / "data" / "processed" / "risk_grid_live.parquet"

    if not live_path.exists():
        return {
            "status": "no_data",
            "message": "Live risk grid not yet computed. Run build_live_risk.py or wait for scheduler.",
            "cell_count": 0,
            "cells": [],
        }

    df = pd.read_parquet(live_path)
    df = df[df["risk_score"] > 0].sort_values("risk_score", ascending=False)
    cells = df.to_dict(orient="records")

    generated_at = cells[0].get("generated_at", "") if cells else ""

    return {
        "status":       "ok",
        "generated_at": generated_at,
        "cell_count":   len(cells),
        "cells":        cells,
    }