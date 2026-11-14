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

Coverage is the sum of original weights for components with a score. If it is
below the configured minimum, the result is `INSUFFICIENT_DATA`, has no numeric
score, and has `INSUFFICIENT` confidence. Otherwise, available component weights
are renormalized as `original weight / available original weight`. A result is
`AVAILABLE` only when coverage is 100%, otherwise `PARTIAL`. Confidence is
computed from coverage thresholds and is stored separately from the score.
Unavailable inputs are never assigned artificial component scores.

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
