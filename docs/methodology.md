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
Covers all 12 months (Jan–Dec 2024) across both Atlantic (Gulf of Maine,
Southeast US) and Pacific (Santa Barbara, Gulf of Farallones, San Pedro
Channel) bounding boxes.

**Vessel Speed Factor (0–1)**
Mean speed (knots) of vessels transiting each cell.
Thresholds based on NOAA research: strikes at >10 knots are almost always fatal.
- ≤10 knots → 0.3
- 10–14 knots → 0.6
- ≥14 knots → 1.0

> **Known limitation:** uses mean speed per cell, which can understate risk
> in cells with a long tail of fast transits. Upgrading to 75th-percentile
> speed is a planned improvement (see Known Limitations).

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

> **Normalization note:** KDE scores are normalized using the 95th percentile
> as the effective ceiling (values above it are clipped to 1.0), rather than
> the raw min/max. This was changed after discovering that a single outlier
> cluster — a large concentration of NARW occurrence records in the Gulf of
> St. Lawrence, an area with no AIS coverage — was dominating the true max
> and silently suppressing presence scores everywhere else in the grid,
> including active US strike zones. Percentile-based normalization prevents
> any one region's survey effort from distorting the scale for the rest of
> the grid. This fix alone raised the medium+ capture rate from 33.8% to
> 61.3% in backtesting.

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

Backtest: 80 curated historical NOAA strike incidents plotted against the
scored grid, now covering all 12 months across both coasts.

- Strikes in grid: 65 / 80 (15 outside current bounding boxes)
- Capture rate (medium+ tier): **61.3%** (49/80)
- Capture rate (high+ tier): 41.2% (33/80)
- Signal ratio: 1.29× (mean score at strike locations vs. mean nonzero cell)

By species:

| Species | Capture rate |
|---|---|
| Blue Whale | 100% (9/9) |
| Fin Whale | 100% (7/7) |
| Humpback Whale | 75.0% (9/12) |
| North Atlantic Right Whale | 64.9% (24/37) |

By month, capture rate ranges from 100% (Aug, Sep, Oct) down to 25% in
June — see Known Limitations for the open investigation into that gap.

## Data Pipeline

```
NOAA AIS CSVs (daily zipped) ───────────────────────────────┐
  → sample 3 days/month, all 12 months                       │
  → clip to bounding boxes (Atlantic + Pacific)               ├─► Shipping density
  → log-normalize vessel counts                              │   (per cell, per month)
                                                             │
aisstream.io WebSocket ──────────────────────────────────────┤
  → live position reports                                    │
  → on-demand 10s snapshot per request                       │
                                                             │
OBIS/GBIF occurrences ──► Gaussian KDE per cell/month ───────┤
  → 95th-percentile normalization                            ├─► Risk grid (Parquet)
NOAA shapefiles ─────────────────────────────────────────────┤   (per month)
  → active month filtering                                   │
  → point-in-polygon for zone overlap                        │
                                                             └─► FastAPI ──► Mapbox frontend
```

## Known Limitations

- Historical AIS data from marinecadastre.gov covers US waters only.
  Global coverage requires AISHub or a commercial feed.
- AIS is sampled (3 days per month) rather than full coverage, across all
  12 months. Full-month AIS would likely increase density scores and
  capture rate further, particularly in sparser months.
- OBIS/GBIF occurrence records are presence-only (no absence data).
  KDE density estimates whale habitat probability, not confirmed absence.
- June (month 06) capture rate is an outlier low at 25%, concentrated in
  Cape Cod Bay and the Bay of Fundy. Shipping density and whale presence
  both compute normally for this month, but the specific strike locations
  don't accumulate enough occurrence signal relative to the surrounding
  region even after percentile normalization. Under investigation — may
  reflect genuine sparsity in OBIS/GBIF survey effort for that window
  rather than a pipeline bug.
- The Gulf of St. Lawrence (up to 50°N) is included in the ocean grid and
  has substantial NARW occurrence data, but no AIS coverage at all (NOAA's
  feed only includes US receivers). Risk scores there are necessarily near
  zero — an accurate reflection of missing shipping data, not a bug. This
  region's outsized occurrence density previously distorted whale presence
  normalization elsewhere in the grid; see the Normalization note above.
- Speed factor uses mean speed per cell rather than 75th percentile.
  Planned upgrade — may better capture cells with a long tail of fast
  transits alongside slower average traffic.
- The risk score is a relative index, not an absolute probability of strike.
  Interpret comparatively (cell A is riskier than cell B), not as a literal
  percentage chance of strike. A methodology tooltip communicating this in
  the UI is planned but not yet implemented.
