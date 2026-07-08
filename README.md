# Whale Ship-Strike Risk Navigator

Live URLs:
- Frontend: https://whale-strike-navigator.vercel.app
- Backend: https://whale-strike-navigator-api.onrender.com
- GitHub: https://github.com/joch1721/whale-strike-navigator

## Current Status

### Completed

- ✅ All 6 phases built and deployed (Vercel + Render)
- ✅ 39,756 ocean grid cells (Atlantic + Pacific bounding boxes)
- ✅ Full 12 months of risk scores computed (Jan–Dec 2024), both coasts
- ✅ 4 species: NARW, Blue, Humpback, Fin
- ✅ Live vessel layer via aisstream.io on-demand WebSocket
- ✅ Species drawer with threats/population/monthly chart
- ✅ Seasonal playback animation across all 12 months
- ✅ Incident click popups
- ✅ Bounding box expanded to 50°N (captures Gulf of St. Lawrence)
- ✅ Pacific bounding box added (Santa Barbara + Gulf of Farallones + San Pedro Channel)
- ✅ Streaming AIS downloads with retry logic (handles large NOAA files reliably)
- ✅ Whale presence KDE normalization fixed (95th-percentile ceiling, prevents
  Gulf of St. Lawrence survey-effort outlier from suppressing signal elsewhere)
- ✅ Dynamic month scrubber (reflects actual available months from API, no
  hardcoded month list to maintain)
- ✅ Custom whale icon set (replaces emoji), updated typography
  (Space Grotesk / IBM Plex Mono)
- ✅ Species panel / risk legend layout fixed with shared flex container
  (panels can no longer overlap regardless of content height)

### Remaining Limitations

| # | Limitation | Status |
|---|---|---|
| 1 | Bounding box too small | ✅ Fixed (50°N + Pacific) |
| 2 | AIS sampled 3 days/month | Still sampled, now across all 12 months |
| 3 | Blue Whale sparse Atlantic records | ✅ Fixed (Pacific bbox) — 100% capture |
| 4 | Gulf of St. Lawrence — no AIS coverage (Canadian waters) | Documented; risk scores there are accurately near-zero |
| 5 | Methodology note in UI (score is relative) | Not yet done |
| 6 | Speed factor uses mean not 75th percentile | Not yet done |
| 7 | June (month 06) capture rate outlier — 25% | Under investigation |

## Backtest Results (current)

- 65/80 strikes in grid (15 outside current bounding boxes)
- Capture rate (medium+): **61.3%** (49/80), up from 30.0% before the
  12-month AIS rebuild and whale presence normalization fix
- Capture rate (high+): 41.2% (33/80)
- Signal ratio: 1.29×
- BLUE: 100% captured (9/9) — up from 0% before Pacific AIS coverage
- FIN: 100% captured (7/7)
- HUMPBACK: 75.0% captured (9/12)
- NARW: 64.9% captured (24/37)
- Weakest month: June at 25% capture — see `docs/methodology.md` Known
  Limitations for details

## Tech Stack

- **Frontend:** React + Vite, Mapbox GL JS, Recharts → Vercel
- **Backend:** Python + FastAPI, GeoPandas, Shapely → Render (free tier)
- **Scheduling:** APScheduler (AIS check every 15 min)
- **Live vessels:** On-demand WebSocket to aisstream.io (~10s collect per request)

## Environment

- macOS, Python 3.12 in `.venv` inside `backend/`
- Always activate: `source .venv/bin/activate` from `backend/`
- Run scripts from `backend/` with `python ../scripts/...`
- Render auto-deploys on push to `main`
- Vercel auto-deploys on push to `main`
- Large commits may need: `git config http.postBuffer 524288000`

## Project Structure

```
whale-strike-navigator/
├── backend/app/
│   ├── main.py               # FastAPI + lifespan
│   ├── config.py             # Settings from .env
│   ├── routers/              # risk, species, incidents, whale_zones, vessels
│   ├── services/             # data_loader, scheduler
│   └── utils/                # cache, logging, species
├── frontend/src/
│   ├── App.jsx               # Main map + all layers
│   └── components/           # SpeciesPanel, SpeciesDrawer, MonthScrubber,
│                              # RiskLegend, StatsBar, WhaleIcon
├── scripts/
│   ├── ingestion/             # fetch_noaa_ais, fetch_whale_occurrences,
│   │                          # fetch_whale_zones, fetch_strike_incidents,
│   │                          # stream_aisstream
│   └── processing/            # build_grid, build_shipping_density,
│                              # build_whale_presence, build_risk_scores,
│                              # backtest_risk_model, build_live_risk,
│                              # validate_spatial_join
├── data/
│   ├── processed/            # grid_cells, risk_grid_*, shipping_density_*,
│   │                         # whale_presence_* (all committed to git)
│   ├── raw/incidents/        # strike_incidents.parquet (committed)
│   ├── raw/whale_occurrences/# species parquets (committed)
│   └── shapefiles/           # narw_sma_zones.* (committed)
└── docs/methodology.md       # Risk formula, limitations, data pipeline
```

## Risk Formula

```
shipping_component = shipping_density × mean(speed_factor, vessel_type_weight)
Risk = shipping_component × whale_presence_probability × 100
```

- Shipping density: log-normalized vessel counts (prevents port dominance)
- Speed factor: ≤10kn→0.3, 10–14kn→0.6, ≥14kn→1.0
- Whale presence: max(KDE score, SMA zone overlap), KDE normalized to
  95th-percentile ceiling
- Tiers: critical≥20.5, high≥15.8, medium≥8.5, low<8.5 (calibrated to p95/p90/p75)

## Next Steps

1. Investigate the June capture-rate gap (Cape Cod Bay / Bay of Fundy)
2. Add methodology tooltip to UI (score is relative, not absolute)
3. Upgrade speed factor from mean to 75th-percentile vessel speed
4. Draft outreach messages for NOAA Fisheries, Cascadia Research Collective,
   Ocean Alliance, Whale Alert, WILDLABS.net
5. Write blog post
