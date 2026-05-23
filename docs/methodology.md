# Methodology

## Risk Score Formula

Each 0.1° × 0.1° ocean grid cell receives a monthly risk score (0–100):

```
shipping_component = shipping_density × mean(speed_factor, vessel_type_weight)
Risk = shipping_component × whale_presence_probability × 100
```

> **Note:** The original formula multiplied all three shipping components together
> (`density × speed × vessel_type`), which caused near-zero scores due to
> triple-multiplication collapse. The revised formula averages speed_factor and
> vessel_type_weight as modifiers to shipping_density, preserving their influence
> while keeping scores in a meaningful range.

### Components

**Shipping Density Score (0–1)**
Vessel count per cell per month, log-normalized across active cells.
Log normalization (log1p + min-max) is used because raw AIS counts are
heavily skewed — major ports dominate, compressing all other cells to ~0
under linear scaling. Vessels counted: cargo, tanker, passenger, high speed.
Fishing and recreational craft downweighted via vessel type weight.

**Vessel Speed Factor (0–1)**
Mean speed (knots) of vessels transiting each cell.
Thresholds based on NOAA research: strikes at >10 knots are almost always fatal.
- ≤10 knots → 0.3
- 10–14 knots → 0.6
- ≥14 knots → 1.0

**Vessel Type Weight (0–1)**
- Tanker / cargo (70–89): 1.0
- High speed craft (40–49): 0.95
- Passenger / cruise (60–69): 0.9
- Fishing (30–35): 0.4
- Tug (52–53): 0.3
- Sailing / pleasure craft (36–37): 0.1
- Unknown (0): 0.5

**Whale Presence Probability (0–1)**
Derived from two sources, combined:
1. OBIS-SEAMAP + GBIF occurrence density (Gaussian KDE per cell, bandwidth=0.5°, per month)
2. NOAA seasonal management zone shapefiles (binary: inside active zone = 1.0)

Combined as: `max(KDE_score, zone_overlap)`

### Risk Tiers

Tiers are calibrated to the empirical score distribution rather than fixed
thresholds, so they reflect relative risk across the actual data:

| Tier | Score | Distribution |
|---|---|---|
| Critical | ≥ 20.5 | top 5% of active cells (p95) |
| High | 15.8 – 20.5 | p90–p95 |
| Medium | 8.5 – 15.8 | p75–p90 |
| Low | < 8.5 | below p75 |

### Validation

Backtest: 80 curated historical NOAA strike incidents plotted against the scored grid.
- Signal ratio: 1.55× (strike locations score 55% higher than average ocean cells)
- In-grid capture rate: 42.6% of strikes inside bounding box scored ≥ medium tier
- 33 of 80 strikes fall outside current bounding box (Pacific, Gulf of St. Lawrence)

## Data Pipeline

```
NOAA AIS CSVs (daily zipped) ───────────────────────────────┐
  → sample 3 days/month                                      │
  → clip to bounding boxes                                   ├─► Shipping density
  → log-normalize vessel counts                              │   (per cell, per month)
                                                             │
aisstream.io WebSocket ──────────────────────────────────────┤
  → live position reports                                    │
  → flush to Parquet every 5 min                             │
                                                             │
OBIS/GBIF occurrences ──► Gaussian KDE per cell/month ───────┤
                                                             ├─► Risk grid (Parquet)
NOAA shapefiles ─────────────────────────────────────────────┤   (per month)
  → active month filtering                                   │
  → point-in-polygon for zone overlap                        │
                                                             │
                                                             └─► FastAPI ──► Mapbox frontend
```

## Known Limitations

- Historical AIS data from marinecadastre.gov covers US waters only.
  Global coverage requires AISHub or a commercial feed.
- AIS is sampled (3 days per month) rather than full coverage.
  Full-month AIS would increase density scores and capture rate.
- OBIS/GBIF occurrence records are presence-only (no absence data).
  KDE density estimates whale habitat probability, not confirmed absence.
- Blue Whale records are sparse in Atlantic bounding boxes (<50 records).
  Pacific Blue Whale coverage requires a West Coast bounding box.
- The risk score is a relative index, not an absolute probability of strike.
  Interpret comparatively (cell A is riskier than cell B), not as a literal
  percentage chance of strike.
- Gulf of St. Lawrence NARW strikes fall outside the current bounding box.
  Expanding north to 50°N would capture these high-value validation points.