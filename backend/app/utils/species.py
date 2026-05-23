"""
Target species definitions — single source of truth for species metadata
used across ingestion scripts, the risk engine, and API responses.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Species:
    key: str               # Short identifier used in filenames and API params
    common_name: str
    scientific_name: str
    gbif_taxon_key: int    # GBIF backbone taxon ID
    obis_aphia_id: int     # WoRMS AphiaID used by OBIS
    iucn_status: str
    est_population_low: int
    est_population_high: int
    population_note: str


SPECIES = {
    "narw": Species(
        key="narw",
        common_name="North Atlantic Right Whale",
        scientific_name="Eubalaena glacialis",
        gbif_taxon_key=2440064,
        obis_aphia_id=159023,
        iucn_status="Critically Endangered",
        est_population_low=360,
        est_population_high=400,
        population_note="Fewer than 70 reproductively active females remain.",
    ),
    "blue": Species(
        key="blue",
        common_name="Blue Whale",
        scientific_name="Balaenoptera musculus",
        gbif_taxon_key=2440717,
        obis_aphia_id=137090,
        iucn_status="Endangered",
        est_population_low=10000,
        est_population_high=25000,
        population_note="Eastern North Pacific population considered Endangered.",
    ),
    "humpback": Species(
        key="humpback",
        common_name="Humpback Whale",
        scientific_name="Megaptera novaeangliae",
        gbif_taxon_key=2440718,
        obis_aphia_id=137092,
        iucn_status="Least Concern",
        est_population_low=120000,
        est_population_high=150000,
        population_note="Arabian Sea subpopulation is Endangered.",
    ),
    "fin": Species(
        key="fin",
        common_name="Fin Whale",
        scientific_name="Balaenoptera physalus",
        gbif_taxon_key=2440714,
        obis_aphia_id=137091,
        iucn_status="Vulnerable",
        est_population_low=80000,
        est_population_high=120000,
        population_note="Mediterranean subpopulation is Endangered.",
    ),
}

SPECIES_KEYS = list(SPECIES.keys())
