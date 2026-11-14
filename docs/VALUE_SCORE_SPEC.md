# Value Score Specification

## Scope and inputs

Value Score v1 combines six independently audited components using versioned
weights: historical price 15%, historical PER/PBR 20%, normalized PER and
EV/EBITDA 25%, cash flow 15%, balance sheet 15%, and relative valuation 10%.
Every component is recorded, including unavailable explanations. The default
minimum original-weight coverage is 65%; confidence boundaries are configurable
and stored in the configuration snapshot.

The calculation uses the requested UTC `as_of` cutoff for every repository
query. Existing valuation percentile and normalized earnings services perform
their existing point-in-time source selection. Input references retain source,
revision, date, and source-record/calculation identity where available. Results
are immutable snapshots; repository operations expose create/read only and do
not commit transactions.

## Formulas and direction

* Historical price: ECDF percentile of the selected close or adjusted close,
  then `100 - percentile`. This describes price history only; a low price rank
  does not prove undervaluation. The series never mixes close bases or market
  sources. Corporate-action comparability depends on the selected adjusted
  series being consistently supplied by its source.
* Historical valuation: arithmetic mean of available `100 - percentile` PER
  and PBR scores. Invalid/negative PER and non-positive book value are excluded
  by the existing valuation calculation/percentile rules, not replaced with 0.
* Normalized valuation: arithmetic mean of available `100 - percentile`
  normalized PER and EV/EBITDA percentiles. Existing Sprint 10/11 window,
  D&A sign, currency, and provenance rules remain authoritative.
* Cash flow: unavailable in v1 because standardized operating cash flow and
  CAPEX inputs are not currently provided. Neither missing input is treated as
  zero and no proxy is fabricated.
* Balance sheet: Debt/Equity, where debt is short-term plus long-term debt and
  equity is total equity. Score is `100 * max(0, 1 - (Debt/Equity)/2)`; the
  upper leverage boundary (configurable `maximum_debt_to_equity`, default 2x)
  scores zero. Zero/negative equity and negative debt are invalid; missing
  inputs are unavailable. This single leverage metric avoids double-counting
  multiple correlated leverage measures.
* Relative valuation: explicitly supplied peers only. Active shared
  sub-industry exposure is required. For each comparable positive multiple,
  score is `100 * peer median / (company multiple + peer median)` (parity = 50).
  Currency, financial period, calculation version, and requested source filters
  must match; insufficient peer samples are unavailable. Peer discovery is
  intentionally not automated.

Each component uses a 0–100 scale, where higher means a more attractive value
signal. Percentile functions are monotonic; the leverage function is linear
with stated endpoints. Input units, validity, missing behavior, and calculation
version are recorded with the measure and score configuration.

## Missing data, coverage, and confidence

Each component records its own submetric coverage. A component with one of two
usable PER/PBR measures has coverage 0.5 and its score is the average of the
usable measure only; an unavailable measure is never set to zero. A component
with all its declared submetrics available has coverage 1. A component with no
usable submetrics has coverage 0 and no score.

Overall data coverage is `sum(original component weight * component coverage)`.
For score aggregation, each scored component's provisional weight is its
original weight multiplied by component coverage; provisional weights are then
normalized to sum to one. Thus a half-covered historical PER/PBR component
contributes half its original weight to the score and overall coverage, while
its score remains the mean of the usable submetric scores. If overall coverage
is below the configured minimum, the result is `INSUFFICIENT_DATA`, has no
numeric score, and has `INSUFFICIENT` confidence. Otherwise, `AVAILABLE` means
coverage is 100%; lower usable coverage is `PARTIAL`. Confidence boundaries
apply to overall data coverage and are stored separately from the numerical
score.

Expected missing data is represented by nullable inputs and explicit statuses:
`BuildValuationInputs` returns missing financial/price values as `None`, while
valuation and percentile services return `UNAVAILABLE` or `INSUFFICIENT_DATA`
results with no numeric value. The Value Score workflow consumes those normal
results directly; it does not use a separate missing-data exception. Domain
validation failures, including source ambiguity, mixed standards/scopes,
currency or unit conflicts, invalid inputs, and PIT violations, propagate and
abort the calculation. The score snapshot is appended only after all components
have completed, and the caller retains transaction ownership.

For legacy snapshots, component coverage is recovered from stored submetrics
when available. A legacy `PARTIAL` component with no measurable submetric
coverage is returned with `coverage = null` (unknown); its stored score, overall
coverage, and weights are left intact. Unknown legacy coverage cannot be used
to recalculate a new aggregate until the caller supplies new inputs.

Peer observations are grouped by exact singleton financial-source and
market-source signature. Cohorts must also match currency, financial period,
and calculation version. Selection is performed independently for PER, PBR,
and EV/EBITDA: the cohort with the most eligible peers for that metric wins,
provided it meets the configured minimum. Ties are broken by ascending
financial source ID, market source ID, currency, period, calculation version,
cutoff, and snapshot ID. This per-metric policy allows a metric with a larger
valid source cohort to contribute even when another metric has less coverage;
it never combines source signatures inside one peer median.

Each selected target and peer valuation snapshot is retained as a
metric-coded input reference. The metric code, security ID, financial source
IDs, and market source ID therefore identify the exact cohort membership and
source signature used by each median, including after persistence round-trip.
The component-level selected-peer list is the union of peers used by its
available metrics. Excluded peers retain their IDs and metric-prefixed reasons,
including when a peer is excluded from more than one metric. Observations with
`available_at > as_of` are excluded before cohort grouping. A peer excluded
from one metric does not invalidate another metric's eligible cohort.

## Persistence and limitations

Snapshots store calculation/configuration versions, all six component results,
effective and original weights, exclusions, measures, and source references in
one append-only result record. A recalculation creates a new row; caller-owned
transactions provide atomicity. Input IDs in JSON are audit references rather
than cross-table cascading foreign keys.

V1 has no standardized cash-flow/CAPEX inputs, no currency conversion, no
automated peer discovery, and no explicit industry-share threshold beyond
requiring a shared active sub-industry. Price history quality and corporate
action adjustment depend on supplied data. These limitations prevent a complete
score whenever those components are unavailable and are reflected in coverage.
