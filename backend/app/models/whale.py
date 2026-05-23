"""
Pydantic models for whale species and occurrence data.
"""

from typing import List, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Species reference data
# ---------------------------------------------------------------------------

SPECIES_CATALOG = {
    "NARW": {
        "common_name": "North Atlantic Right Whale",
        "scientific_name": "Eubalaena glacialis",
        "population_estimate": 400,
        "population_trend": "decreasing",
        "iucn_status": "Critically Endangered",
        "primary_threats": ["Ship strikes", "Entanglement in fishing gear"],
        "typical_length_m": 14.0,
        "typical_mass_tonnes": 70.0,
        "gbif_taxon_key": 2440604,
        "obis_aphia_id": 159023,
        "color_hex": "#E63946",  # red — critically endangered
    },
    "BLUE": {
        "common_name": "Blue Whale",
        "scientific_name": "Balaenoptera musculus",
        "population_estimate": 17500,
        "population_trend": "increasing",
        "iucn_status": "Endangered",
        "primary_threats": ["Ship strikes", "Climate change", "Noise pollution"],
        "typical_length_m": 25.0,
        "typical_mass_tonnes": 150.0,
        "gbif_taxon_key": 2440718,
        "obis_aphia_id": 137090,
        "color_hex": "#457B9D",  # blue
    },
    "HUMPBACK": {
        "common_name": "Humpback Whale",
        "scientific_name": "Megaptera novaeangliae",
        "population_estimate": 80000,
        "population_trend": "increasing",
        "iucn_status": "Least Concern",
        "primary_threats": ["Entanglement", "Ship strikes", "Noise pollution"],
        "typical_length_m": 15.0,
        "typical_mass_tonnes": 36.0,
        "gbif_taxon_key": 2440714,
        "obis_aphia_id": 137092,
        "color_hex": "#2A9D8F",  # teal
    },
    "FIN": {
        "common_name": "Fin Whale",
        "scientific_name": "Balaenoptera physalus",
        "population_estimate": 100000,
        "population_trend": "increasing",
        "iucn_status": "Vulnerable",
        "primary_threats": ["Ship strikes", "Legacy whaling impacts", "Climate change"],
        "typical_length_m": 20.0,
        "typical_mass_tonnes": 70.0,
        "gbif_taxon_key": 2440723,
        "obis_aphia_id": 137091,
        "color_hex": "#E9C46A",  # gold
    },
}


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class WhaleOccurrence(BaseModel):
    """A single whale sighting / occurrence record."""

    occurrence_id: str
    species_code: str  # NARW | BLUE | HUMPBACK | FIN
    scientific_name: str
    lat: float
    lon: float
    date: str          # YYYY-MM-DD
    month: int         # 1–12, derived from date
    source: str        # GBIF | OBIS | WhaleAlert
    record_type: str   # observation | acoustic | stranding | strike
    individual_count: Optional[int] = None
    data_quality: Optional[str] = None  # GBIF issue flags etc.


class WhaleZone(BaseModel):
    """A NOAA seasonal management zone polygon."""

    zone_id: str
    species_code: str
    zone_name: str
    active_months: List[int]  # e.g. [11, 12, 1, 2, 3, 4] for Nov–Apr
    geometry_geojson: dict    # GeoJSON polygon/multipolygon
    regulatory: bool = True   # True = IMO/NOAA enforceable zone
    speed_limit_knots: Optional[float] = 10.0


class SpeciesInfo(BaseModel):
    """Full species reference card for the UI species panel."""

    code: str
    common_name: str
    scientific_name: str
    population_estimate: int
    population_trend: str
    iucn_status: str
    primary_threats: List[str]
    typical_length_m: float
    typical_mass_tonnes: float
    color_hex: str


class StrikeIncident(BaseModel):
    """A confirmed NOAA ship strike incident."""

    incident_id: str
    species_code: Optional[str] = None
    species_name: Optional[str] = None
    lat: float
    lon: float
    date: str
    year: int
    month: Optional[int] = None
    vessel_type: Optional[str] = None
    vessel_length_m: Optional[float] = None
    vessel_speed_knots: Optional[float] = None
    outcome: Optional[str] = None  # lethal | injurious | unknown
    source: str = "NOAA"
