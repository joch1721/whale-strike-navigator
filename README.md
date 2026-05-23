# 🐋 Whale Ship-Strike Risk Navigator

An open, continuously-updated tool showing where global shipping lanes and whale habitats dangerously overlap — visualized on a live map with real-time risk scoring.

## Why This Exists

North Atlantic Right Whales are down to ~400 individuals. Ship strikes are one of the leading causes of death. NOAA and IMO assess risk manually and seasonally. This tool makes that risk visible, live, and public.

## Target Species

| Species | Est. Population | IUCN Status |
|---|---|---|
| North Atlantic Right Whale | ~400 | Critically Endangered |
| Blue Whale | 10,000–25,000 | Endangered |
| Humpback Whale | ~135,000 | Least Concern (some subpops endangered) |
| Fin Whale | ~100,000 | Vulnerable |

## Data Sources

| Data | Source |
|---|---|
| AIS Shipping (historical) | [NOAA MarineCadastre](https://marinecadastre.gov/ais/) |
| AIS Shipping (live) | [aisstream.io](https://aisstream.io) |
| Whale occurrences | [OBIS-SEAMAP](https://seamap.env.duke.edu), [GBIF](https://www.gbif.org) |
| Right Whale zones | [NOAA Fisheries Shapefiles](https://www.fisheries.noaa.gov) |
| Strike incidents | Curated from Jensen & Silber (2003), Laist et al. (2001), NOAA UME reports |

## Tech Stack

- **Frontend:** React + Vite, Mapbox GL JS, Recharts
- **Backend:** Python + FastAPI, GeoPandas, Shapely
- **Scheduling:** APScheduler (AIS refresh every 15 min)
- **Deployment:** Vercel (frontend) + Render (backend)

## Risk Score Formula

```
shipping_component = shipping_density × mean(speed_factor, vessel_type_weight)
Risk = shipping_component × whale_presence_probability × 100
```

Normalized to 0–100 using log normalization on vessel counts (prevents port dominance skew).
Computed per 0.1° × 0.1° grid cell, per month.

### Risk Tiers (calibrated to score distribution)
| Tier | Score | Threshold |
|---|---|---|
| Critical | ≥ 20.5 | p95 of active cells |
| High | 15.8 – 20.5 | p90 |
| Medium | 8.5 – 15.8 | p75 |
| Low | < 8.5 | below p75 |

## Build Status

- [x] Phase 1.1 — Project scaffold
- [x] Phase 1.2 — NOAA AIS ingestion (6 months, log-normalized)
- [x] Phase 1.3 — Whale occurrence data (GBIF + OBIS, 4 species)
- [x] Phase 1.4 — NOAA Right Whale shapefiles (10 SMA zones)
- [x] Phase 1.5 — Historical strike incidents (80 curated)
- [x] Phase 1.6 — Spatial join validation (1.55x signal ratio)
- [x] Phase 2.1 — Grid cell definition (35,624 ocean cells)
- [x] Phase 2.2 — Shipping density layer (log-normalized, per month)
- [x] Phase 2.3 — Whale presence probability (KDE + zone overlap)
- [x] Phase 2.4 — Composite risk formula (0–49.5 score range)
- [x] Phase 2.5 — Backtest against strike incidents
- [x] Phase 3.1 — FastAPI endpoints (risk, species, incidents, zones, vessels)
- [x] Phase 3.2 — Caching (TTLCache) + APScheduler (15 min AIS refresh)
- [x] Phase 4.1 — React + Vite scaffold
- [x] Phase 4.2 — Shipping density heatmap layer
- [x] Phase 4.3 — Whale zone polygons
- [x] Phase 4.4 — Risk overlap layer
- [x] Phase 4.5 — Incident markers with click popup
- [x] Phase 4.6 — Controls (month scrubber, species filter, live toggle)
- [x] Phase 5.1 — Species panel with detail drawer
- [x] Phase 5.2 — Seasonal playback animation
- [x] Live vessel layer (aisstream.io WebSocket collector)
- [ ] Phase 6.1 — Live AIS → risk score integration
- [ ] Phase 6.2 — Frontend deployment (Vercel)
- [ ] Phase 6.3 — Backend deployment (Render)
- [ ] Phase 6.4 — README + blog post
- [ ] Phase 6.5 — Outreach

## License

MIT — open source, open data, open ocean.