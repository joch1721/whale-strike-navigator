"""
routers/species.py
------------------
GET /species       — list all target species with metadata
GET /species/{key} — single species detail card
"""

from fastapi import APIRouter, HTTPException
from app.utils.species import SPECIES
from app.models.whale import SPECIES_CATALOG

router = APIRouter()

# Merge species.py metadata with whale.py catalog for full detail
def build_species_response(sp, key: str) -> dict:
    catalog = SPECIES_CATALOG.get(key.upper(), {})
    return {
        "key":                 sp.key,
        "common_name":         sp.common_name,
        "scientific_name":     sp.scientific_name,
        "iucn_status":         sp.iucn_status,
        "est_population_low":  sp.est_population_low,
        "est_population_high": sp.est_population_high,
        "population_note":     sp.population_note,
        "gbif_taxon_key":      sp.gbif_taxon_key,
        "obis_aphia_id":       sp.obis_aphia_id,
        # From whale catalog
        "primary_threats":     catalog.get("primary_threats", []),
        "typical_length_m":    catalog.get("typical_length_m"),
        "typical_mass_tonnes": catalog.get("typical_mass_tonnes"),
        "color_hex":           catalog.get("color_hex"),
    }


@router.get("")
async def list_species():
    return {
        "species": [
            build_species_response(sp, key)
            for key, sp in SPECIES.items()
        ]
    }


@router.get("/{key}")
async def get_species(key: str):
    sp = SPECIES.get(key.lower())
    if not sp:
        raise HTTPException(
            status_code=404,
            detail=f"Species '{key}' not found. Valid keys: {list(SPECIES.keys())}",
        )
    return build_species_response(sp, key)