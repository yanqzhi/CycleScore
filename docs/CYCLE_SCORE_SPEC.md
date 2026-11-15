# Cycle Score Specification — Earnings Cycle v1

## Purpose and boundary

Cycle Score v1 is a **company earnings-cycle proxy**. It estimates the direction,
turning behavior, and historical position of annual operating profit. It is
independent from Value Score and does not measure whether a share is cheap.

This is not a complete industry-cycle model. It does not yet use inventory,
orders, utilization, commodity prices, capacity, supply-demand balance, or
industry clearing data. Company-level consolidated earnings are never multiplied
by an industry revenue exposure and presented as segment earnings. Future cycle
signals must enter as their own source-scoped observations and components.

## Input series and point-in-time policy

`CalculateCycleScore` delegates annual statement assembly to the existing
`CalculateNormalizedEarnings` use case and analyzes its persisted
`OPERATING_PROFIT.fiscal_year_values`. It does not use the normalized arithmetic
mean as a synthetic annual observation. The requested window is 5, 7, or 10
fiscal years. Its boundaries come from eligible annual FY statements visible to
the normalized earnings service; an FY with no operating-profit value remains a
missing observation and lowers coverage.

The normalized earnings service enforces one source when selected, and rejects
ambiguous multiple sources or mixed accounting standard, consolidation scope,
or reporting currency. Cycle Score rechecks source references and requires FY
operating-profit lines. No currency conversion or implicit source mixing is
performed. When a security ID is supplied, it must belong to the requested
company. The same request `as_of` is used throughout:

- statement `available_at <= as_of`;
- financial period end is no later than the cutoff date;
- revision selection occurs after availability filtering;
- `collected_at` is not used to determine historical visibility.

Each score records its normalized earnings result ID and the exact statement
line, statement, source, revision, fiscal year, period, currency, and availability
time for every annual observation. A historical score is reconstructed by
running the normalized earnings use case at that historical cutoff, never by
using current statements. The caller-owned transaction includes newly created
normalized earnings results and the Cycle Score snapshot.

## Annual observations, missing periods, and calculations

Only reported FY operating-profit values are used. Negative and zero values are
valid observations; no percentage growth rate is calculated. Observations are
sorted by fiscal year and duplicate fiscal years or incompatible source metadata
are fatal integrity errors. Missing FYs are not filled with zero.

For the observation series `(year_i, earnings_i)`, the annual trend slope is the
ordinary least-squares slope against the actual fiscal year. For a selected
window, define `scale = max(abs(earnings_i))`; when this is zero, normalized
slopes are zero.

1. **Recent earnings momentum** is the OLS slope of the latest
   `recent_observation_count` observations divided by `scale`.
2. **Earnings acceleration** splits the ordered observations at
   `floor(n / 2)`. The earlier segment includes observations through the split;
   the recent segment starts at the split, so they share one boundary
   observation. Acceleration is `(recent slope - earlier slope) / scale`.
3. **Historical earnings position** is
   `(latest earnings - window minimum) / (window maximum - window minimum)`.
   It is `0.5` for a flat range. Negative observations remain in the range.
4. **Trend confirmation** uses consecutive pairs among the latest configured
   observations. Each pair's change is divided by its actual year gap. It is the
   fraction of observed changes with the same sign as the recent OLS slope;
   unchanged pairs do not support a direction. Missing years are not inserted.

All calculations use `Decimal`; internal trend calculations use a 50-digit
local context, and stored component and total scores use seven decimal places,
rounded half-even.

## Default configuration and score formula

All thresholds, weights, phase scores, observation counts, and window size are
part of the versioned `CycleScoreConfig` snapshot. The v1 defaults are:

| Component | Weight | Score calculation |
| --- | ---: | --- |
| Earnings momentum | 0.35 | `50 + 50 × clamp(recent_momentum / 0.20, -1, 1)` |
| Earnings acceleration | 0.25 | `50 + 50 × clamp(acceleration / 0.10, -1, 1)` |
| Historical position | 0.15 | Configured score for the inferred phase; 50 for UNKNOWN |
| Trend confirmation | 0.25 | Rising: `50 + 50 × confirmation`; falling: `50 - 50 × confirmation`; flat: 50 |

The total is the weighted sum using the configured weights (0.35, 0.25, 0.15,
0.25). Weights are not redistributed when data is missing. The minimum sample is
five observations and minimum coverage is 0.60. A score is withheld when either
gate fails. The default analysis window is seven years and the latest three
observations form the recent trend.

The default classification thresholds are a normalized momentum deadband of
0.02, acceleration deadband of 0.01, low-position boundary of 0.25, high-position
boundary of 0.75, and minimum trend confirmation of 0.60. The normalized full
scales are 0.20 for momentum and 0.10 for acceleration. Phase-to-position scores
are configurable: EARLY_RECOVERY 70, EXPANSION 85, PEAK 35, CONTRACTION 25,
TROUGH 45, UNKNOWN 50.

## Phase classification

Rules are evaluated in this order:

1. **TROUGH** requires a low position (`<= 0.25`), negative full-window
   momentum, recent momentum inside the deadband, positive acceleration above
   its deadband, and the last two observed annual changes non-falling with at
   least one strictly positive change. A low earnings level or still-falling
   series alone cannot be a trough.
2. A recent trend whose confirmation is below the configured minimum is
   **UNKNOWN**.
3. **EARLY_RECOVERY** requires low position and recent momentum above the
   positive deadband with sufficient confirmation.
4. **EXPANSION** requires recent momentum above the positive deadband with
   sufficient confirmation and position above the low boundary. This includes
   high earnings that continue to improve.
5. **PEAK** requires high position (`>= 0.75`) and recent momentum below the
   negative deadband with sufficient confirmation.
6. **CONTRACTION** is a confirmed recent decline that did not meet the peak or
   trough rules. Thus low earnings that continue to deteriorate are contraction.
7. Flat momentum inside the deadband or conflicting full-window and recent
   trends outside the low-earnings zone are **UNKNOWN**.

TROUGH describes a confirmed near-low stabilization/turning zone while earnings
remain depressed. EARLY_RECOVERY describes subsequent positive recent momentum
from that low zone. These are earnings-pattern labels, not claims about inventory
or industry supply-demand turning points.

## Coverage, status, and confidence

Data coverage is `observed FY operating-profit count / number of fiscal-year
labels in the normalized earnings window`. It is unknown when there is no
eligible annual statement window; it is zero when a known window has no usable
operating-profit lines. Component coverage records this same source-series
coverage independently of each component score.

- Fewer than five observations or coverage below 0.60: `INSUFFICIENT_DATA`, no
  total/component scores, `UNKNOWN` phase, `INSUFFICIENT` confidence.
- Sufficient data and a classified phase: `AVAILABLE`.
- Sufficient numeric trend evidence but `UNKNOWN` phase: `PARTIAL`; the
  directional score remains available, the historical-position component uses
  the configured neutral UNKNOWN score, and confidence is `LOW`.
- `HIGH` confidence requires at least seven observations and coverage at least
  0.85. `MEDIUM` requires coverage at least 0.70. Other sufficient samples are
  `LOW`.

Coverage, confidence, phase, and score are persisted separately. Missing
earnings are never changed to zero. Weights are never reallocated in v1.

## Persistence and limitations

Cycle Score snapshots are append-only and contain their exact config snapshot,
component values and scores, coverage, confidence, phase and reason, selected
source/currency, normalized-result identity, and annual statement provenance.
The SQLAlchemy repository exposes create/read operations only and does not
commit. A failed transaction rolls back both normalized results generated for
the request and the score.

Annual statements are lagging and may be revised. The model uses one primary
financial metric and can be sensitive to accounting changes, acquisitions,
disposals, exceptional items, fiscal-year changes, and missing history. It is
not a full cycle score and is not an investment recommendation. Later sprints
may add independent inventory, supply-demand, commodity-price, and capacity
signals with their own PIT contracts and versioned weights.
