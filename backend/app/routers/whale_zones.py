"""
routers/whale_zones.py
----------------------
GET /whale-zones  — NOAA NARW Seasonal Management Area polygons
"""

from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from app.services.data_loader import get_whale_zones, is_data_loaded
from app.utils.cache import cached

router = APIRouter()


@router.get("")
@cached(ttl=3600)
async def list_whale_zones(
    month: Optional[int] = Query(None, ge=1, le=12),
):
    """
    Return NARW SMA polygons as GeoJSON. Cached 1 hour — zones don't change.
    """
    if not is_data_loaded():
        raise HTTPException(status_code=503, detail="Data not yet loaded")

    gdf = get_whale_zones(month=month)

    if gdf.empty:
        return {
            "type": "FeatureCollection",
            "features": [],
            "month_filter": month,
            "zone_count": 0,
        }

    features = []
    for _, row in gdf.iterrows():
        try:
            geom = row.geometry.__geo_interface__
        except Exception:
            continue
        features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "zone_name":         row.get("zone_name", ""),
                "species_code":      row.get("species_code", "NARW"),
                "active_months":     row.get("active_months", []),
                "speed_limit_knots": row.get("speed_limit_knots", 10.0),
                "regulatory":        row.get("regulatory", True),
                "source":            row.get("source", "NOAA"),
            },
        })

    return {
        "type": "FeatureCollection",
        "month_filter": month,
        "zone_count": len(features),
        "generated_at": datetime.utcnow().isoformat(),
        "features": features,
    }
