# Industry Inventory Engine v1

Sprint 18 analyzes existing Sprint 17 industry signal aggregate snapshots. It
does not aggregate raw constituents, infer demand, or calculate capacity or
supply-demand balances. The engine is descriptive and its labels are not
investment signals.

The separate `inventory_trend` is the direction of the adjacent absolute
inventory change: `INCREASING`, `DECREASING`, `STABLE` for exactly zero, or
`UNKNOWN` when the adjacent comparison is missing. It does not replace the
cycle classification.

## Inputs and temporal rules

Inventory is a `POINT` balance. Production and shipments are `PERIOD` flows.
The engine accepts the existing signal temporal kinds, but v1 uses inventory
point observations and may use production/shipments only when both flow periods
have the same start and end and end exactly on the inventory observation date.
Their difference is retained as a production-shipment gap diagnostic; it is not
treated as inventory change.

YoY inventory growth is `(current inventory / inventory on exact calendar
anniversary) - 1`. A February 29 observation has no prior-year match in a
non-leap year; v1 does not silently substitute February 28 or March 1. A zero
or missing prior-year balance makes YoY unavailable. The preceding observation
is the latest earlier eligible point in the same cohort. Growth acceleration
is current YoY less the previous observation's own exact-anniversary YoY.
Missing periods are never filled with zero or interpolated.

All inputs must share industry/sub-industry, aggregate region, complete exact
requested constituent scope, source, unit, currency, and classification
references. The scope is selected explicitly and is not expanded through region
relationships. A source-less or mixed-source aggregate is not eligible. A
single unambiguous cohort is required; if several source/classification
cohorts remain, the caller must select a source. Revisions are resolved by the
latest eligible aggregate snapshot for each observation date, ordered by
`(as_of, snapshot_id)` after PIT filtering.

## Point-in-time and provenance

For a UTC-normalized `as_of`, aggregate `as_of` and every included contributor's
`available_at` must be no later than the cutoff. Observation dates and period
ends must not exceed the UTC cutoff date. `collected_at` is retained in the
Sprint 17 aggregate audit but is never used for historical visibility. The
engine records every aggregate snapshot used, its role, source, period/date,
availability, and underlying observation IDs.

## Classification v1

The versioned `IndustryInventoryConfig` requires every threshold explicitly
and stores its full values with each snapshot. No numerical defaults are
provided because no industry calibration data or policy was provided. An
operator must select and version a calibrated configuration. The parameters
have these meanings:

| Parameter | Meaning |
|---|---|
| `accumulation_yoy` | Minimum YoY growth for accumulation |
| `rapid_accumulation_yoy` | Minimum YoY growth for rapid accumulation; must exceed the accumulation threshold |
| `normalization_prior_yoy` | Maximum prior comparable growth for identifying a prior correction |
| `normalization_growth_ceiling` | Maximum current YoY growth considered near-normal after correction |
| `stable_growth_tolerance` | Acceleration magnitude treated as stable; negative acceleration beyond it is deceleration |
| `gap_ratio_tolerance` | Production-shipment gap tolerance as a share of current inventory |
| `minimum_coverage` | Minimum region coverage for a usable classification |

Precedence is deterministic. `DRAWDOWN` requires negative absolute change and
negative YoY together with shipments exceeding production beyond the configured
gap tolerance. `NORMALIZATION` requires a prior material contraction,
inventory building again, improving growth within the configured near-normal
ceiling, and a near-balanced matching flow gap. `RAPID_ACCUMULATION` requires
inventory to build, YoY at or above the rapid threshold, and production to
exceed shipments beyond tolerance. `DECELERATING` means YoY is still positive
but its change is below the negative deceleration tolerance; it is not called a
drawdown. `ACCUMULATION` requires positive absolute change, sufficient positive
YoY, and no materially negative matching flow gap. All other cases are
`UNKNOWN`. Slower growth alone never establishes recovery or normalization.

## Availability, coverage, and confidence

Missing evidence remains null and carries a reason. Coverage is copied from the
current aggregate's explicit regional coverage. Below the configured minimum,
status and classification are `INSUFFICIENT_DATA` and `UNKNOWN`. Complete
coverage with all comparison and flow evidence is `AVAILABLE`; otherwise
adequately covered results are `PARTIAL`. Confidence is a separate bounded
value: regional coverage multiplied by evidence coverage (the v1 policy
deducts 0.20 for missing previous comparable YoY, 0.20 for missing exact-period
flow gap, and 0.10 for missing adjacent inventory change). It is not the score
or classification.

## Numeric and persistence rules

Calculations use Decimal local precision and do not convert through float.
Intermediate arithmetic is not rounded; outputs are rounded half-even once to
12 fractional places and checked against `NUMERIC(38,12)`. Arithmetic errors
become domain validation errors. Analysis snapshots, configuration snapshots,
requested scope, and input references are append-only. Recalculation creates a
new row. Application use cases flush through repositories but never commit;
callers own transaction boundaries.

## Limitations

Signal records do not define a canonical publication frequency or industry
trading calendar, so exact calendar anniversaries are the only supported YoY
pairing. Regional coverage quality depends on the configured Sprint 17 scope.
Region activity has no historical validity intervals. Thresholds require
domain calibration. Flow gaps are diagnostics, not
physical inventory balance reconciliation. No currency conversion, inferred
scope, company-level inference, forecasting, or supply-demand engine is
implemented.
