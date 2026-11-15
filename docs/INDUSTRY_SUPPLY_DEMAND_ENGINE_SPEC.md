# Industry Supply & Demand Engine v1

-   Project: CycleScore
-   Sprint: 19
-   Status: Implementation baseline
-   Dependencies: Sprint 15 Industry Signal Data Foundation; Sprint 16
    Classification & Region Master; Sprint 17 Industry Signal
    Aggregation; Sprint 18 Industry Inventory Engine.
-   Purpose: descriptive industry-level supply-demand analysis, not an
    investment signal.

## 1. Purpose and boundaries

Combine persisted Sprint 17 `IndustrySignalAggregateSnapshot` records
with Sprint 18 `IndustryInventorySnapshot` records. Distinguish
production/shipments flow imbalance, shipment demand direction, and
inventory-cycle context. Do not re-aggregate raw observations or
recalculate inventory.

In scope: - Read PIT-compatible PRODUCTION and SHIPMENTS aggregates. -
Pair exact matching flow periods and compatible cohorts. - Calculate
production minus shipments and normalized flow-gap ratio. - Calculate
shipment YoY only from an exact comparable prior-year period. - Reuse
compatible Sprint 18 inventory context. - Apply explicit versioned
classification thresholds. - Persist append-only results with
input/scope provenance and reasons. - Add Domain, Application,
Infrastructure, migration, tests, and docs.

Out of scope: - Raw signal aggregation or modifications to Sprint 17. -
Changes/duplication of Sprint 18 inventory calculations. - Orders/Sales
fallback demand metrics in v1. - Capacity
utilization/additions/closures/capacity clearing. - Forecasting, company
allocation, investment recommendations, scoring/ranking, screening,
backtesting, GUI, Telegram, OpenAI, live providers. - Currency/unit
conversion, seasonal adjustment, interpolation, annualization, inferred
missing values.

## 2. Architecture contracts

Follow the existing modular monolith: - `domain/entities`: immutable
dataclasses, enums, validation. - `domain/services`: pure calculation;
no SQLAlchemy/pandas/provider imports. -
`domain/repositories/contracts.py`: Domain repository contract. -
`application/dto`: typed request/response DTOs. -
`application/use_cases`: orchestration and repository access. -
`infrastructure/database/models`: SQLAlchemy models. -
`infrastructure/database/repositories`: explicit ORM/Domain mapping. -
`migrations/versions`: additive Alembic migration. - `tests/unit` and
`tests/integration`: pure Domain and real SQLite tests.

Repositories/use cases flush but never commit. The caller owns
transaction boundaries.

## 3. Domain vocabulary

Add: - `IndustrySupplyDemandPhase`: `DEMAND_RECOVERY`, `EXPANSION`,
`BALANCED`, `OVERSUPPLY`, `DEMAND_SLOWDOWN`, `UNDERSUPPLY`, `UNKNOWN`. -
`IndustrySupplyDemandStatus`: `AVAILABLE`, `PARTIAL`,
`INSUFFICIENT_DATA`. - `IndustrySupplyDemandConfig`. -
`IndustrySupplyDemandInputReference`. - `IndustrySupplyDemandSnapshot`.

All phase labels are descriptive, not investment signals. `UNKNOWN` is
required when evidence is insufficient or contradictory.

### Configuration

Config fields (all required; no production defaults): - `version: int`
(positive) - `minimum_coverage: Decimal` in \[0,1\] -
`flow_gap_tolerance: Decimal` in \[0,1\] -
`strong_demand_growth: Decimal` \>= 0 -
`negative_demand_growth: Decimal` \<= 0 -
`inventory_accumulation_yoy: Decimal` \>= 0 -
`inventory_drawdown_yoy: Decimal` \<= 0 -
`minimum_evidence_coverage: Decimal` in \[0,1\]

All values must be finite Decimals. Store the complete config snapshot.
No hidden thresholds or weights. Test fixtures may provide explicit
values; production callers must make an explicit calibrated choice.

## 4. Input selection and compatibility

### Aggregate inputs

Use the existing
`IndustrySignalAggregateRepository.list_by_industry(industry_id, as_of=...)`
to load candidates. Required types are `PRODUCTION` and `SHIPMENTS`,
both `PERIOD`.

A candidate must have: - persistent ID and non-null value; - status
other than `INSUFFICIENT_DATA`; - `scope_complete=True`; - explicit
non-null source ID; - aggregate `as_of <= request.as_of`; - period end
no later than the UTC date of `as_of`; - every included contributor
`available_at <= as_of`; - included contributor source IDs equal to
aggregate source ID.

Never use `collected_at` for PIT visibility.

### Exact same-period flow pair

Production and shipments must match exactly on: -
industry/sub-industry; - aggregate region ID and code; - complete
requested constituent identities; - source ID; - period start and end; -
unit and currency; - classification version/mapping cohort; -
aggregation policy code, policy version, and calculation version.

Actual included measurement-region identities (ID and code) must also
match exactly. Both coverage values must be known and equal. Requested
scope equality alone is insufficient.

No cross-source blending. If multiple compatible source cohorts remain
without explicit source selection, return an ambiguity error; never
choose a provider implicitly.

Within each cohort and period, choose the latest eligible snapshot
deterministically by `(as_of, id)` after PIT filtering.

### Inventory context

Use existing
`IndustryInventoryRepository.list_by_industry(industry_id, as_of=...)`.
A compatible inventory snapshot must: - have ID and
`as_of <= request.as_of`; - have
`observation_date == flow period_end`; - match industry/sub-industry,
aggregate region, source, unit, currency, and requested scope; - have
actual contributing regions matching the flow pair; - reference the
exact production and shipments aggregate IDs in `input_references` with
roles `PRODUCTION` and `SHIPMENTS`; - not be `INSUFFICIENT_DATA`.

Otherwise retain it as excluded provenance with a reason. No
nearest-date or alternate-cohort substitution.

### Prior-year pair

Shipment YoY is available only when the prior-year production/shipments
pair: - has the same cohort signature; - has exact calendar
anniversaries for both period start and end; - has identical period
duration; - passes all same-period compatibility rules; - has matching
actual region composition and known coverage; - matches source,
unit/currency, classification, policy version, and calculation version.

Do not substitute Feb 28/March 1 for Feb 29, use nearest periods,
interpolate, or annualize. Missing prior-year pair means YoY is null
with a reason.

## 5. Calculations

Use Decimal only. Use expanded `localcontext()` precision. Round only at
the result boundary using `ROUND_HALF_EVEN` to 12 fractional places.
Validate finite values and \<=26 integer digits for `NUMERIC(38,12)`.
Convert Decimal arithmetic exceptions to `DomainValidationError`.

Let `P_t` and `S_t` be current paired production and shipments; `S_y` is
prior-year shipments.

-   `flow_gap = P_t - S_t`
-   When `S_t > 0`: `flow_gap_ratio = (P_t - S_t) / S_t`; otherwise
    unavailable.
-   When valid prior-year pair exists and `S_y > 0`:
    `shipment_growth_yoy = (S_t / S_y) - 1`; otherwise unavailable with
    reason.

Production minus shipments is a flow diagnostic, **not** physical
inventory change. Negative/zero denominators must not be forced into
valid ratios.

Copy compatible Sprint 18 context only: inventory classification, trend,
inventory YoY growth, growth acceleration, coverage/confidence, and
snapshot ID. Do not recalculate these fields.

## 6. Classification policy

Apply this deterministic precedence and exact boundary semantics:

1.  `INSUFFICIENT_DATA` / `UNKNOWN` if no valid current flow pair,
    current values are unavailable, coverage is unknown, or coverage is
    below `minimum_coverage`.
2.  `OVERSUPPLY` if `flow_gap_ratio > flow_gap_tolerance` and at least
    one corroboration exists: shipment growth `< 0` OR inventory YoY
    `>= inventory_accumulation_yoy`.
3.  `UNDERSUPPLY` if `flow_gap_ratio < -flow_gap_tolerance` and at least
    one corroboration exists: shipment growth `>= strong_demand_growth`
    OR inventory YoY `<= inventory_drawdown_yoy`.
4.  `DEMAND_RECOVERY` if gap ratio is within tolerance, shipment growth
    `>= strong_demand_growth`, and inventory context is `DRAWDOWN` or
    inventory YoY `<= inventory_drawdown_yoy`.
5.  `DEMAND_SLOWDOWN` if shipment growth `<= negative_demand_growth` and
    neither oversupply nor undersupply applies.
6.  `EXPANSION` if gap ratio is within tolerance, shipment growth
    `>= strong_demand_growth`, and no qualifying inventory drawdown
    condition exists.
7.  `BALANCED` if gap ratio is within tolerance, shipment growth is
    strictly between negative and strong thresholds, and there is no
    contradictory inventory condition.
8.  Otherwise `UNKNOWN`.

Oversupply/undersupply require corroboration; a large flow gap alone is
insufficient. Recovery is not inferred from inventory alone. Missing
evidence cannot be treated as zero. Continue to a later branch only if
that branch's required evidence is available; otherwise return
`UNKNOWN`. Unit tests must cover every threshold equality edge.

## 7. Coverage, confidence, status

Keep independent: - `coverage`: regional coverage of the current paired
aggregates; known only when both coverage values are known and equal. -
`evidence_coverage`: fraction of evidence groups available: current flow
pair, prior-year pair, compatible inventory context. - `confidence`:
`NULL` in v1; do not copy coverage/evidence coverage into confidence.

Status: - `INSUFFICIENT_DATA`: no valid current pair or coverage below
minimum; phase `UNKNOWN`. - `AVAILABLE`: all three evidence groups
available and regional coverage exactly 1. - `PARTIAL`: valid current
pair and coverage meets minimum, but optional evidence is missing or
coverage \< 1.

Missing data remains null with explicit reasons.

Implementation clarification: `minimum_evidence_coverage` is an explicit
classification evidence floor. If evidence coverage is below this configured
floor, phase classification remains `UNKNOWN`; it does not promote missing
groups to zero or fabricate evidence. Status still follows the stated status
rules, so a result may be `PARTIAL` while its phase is `UNKNOWN`. This keeps
the numerical coverage, evidence completeness, and confidence (unknown in v1)
as separate concepts. No empirical threshold calibration is supplied by the
engine; the caller must pass and version the chosen configuration.

## 8. Snapshot and persistence

Snapshot should retain: - industry/sub-industry; - aggregate region
ID/code and exact requested scope; - source, unit, currency; - period
start/end and observation date (period end); - `as_of`,
`calculated_at`; - phase/status; - production, shipments, flow gap,
flow-gap ratio, shipment YoY; - copied inventory context and inventory
snapshot ID; - coverage, evidence coverage, confidence; - config version
and full config snapshot; - input references for current
production/shipments, prior-year production/shipments, inventory
snapshot; - candidate inclusion/exclusion reasons; - actual contributor
region identities, coverage, source, periods, aggregate IDs, contributor
observation/revision references; - unavailable reasons and validation
warnings.

Proposed append-only tables: - `industry_supply_demand_snapshots` -
`industry_supply_demand_inputs` - `industry_supply_demand_scopes`

Use `NUMERIC(38,12)` for Decimal outputs and `NUMERIC(8,7)` for bounded
ratios. Use appropriate RESTRICT foreign keys and deterministic indexes.
Store config/reasons using existing JSON conventions. Migration must be
additive and use the actual current Alembic head; inspect before
choosing `down_revision` (do not assume 0026).

## 9. Repository and Application contracts

Add `IndustrySupplyDemandRepository`: - `create(snapshot) -> snapshot` -
`get_by_id(snapshot_id) -> snapshot | None` -
`list_by_industry(industry_id, *, as_of=None) -> list[snapshot]`

SQLAlchemy adapter must map explicitly, persist snapshot/scopes/inputs
atomically in caller transaction, flush only, and reconstruct
deterministic order.

Add typed request/response DTOs and `AnalyzeIndustrySupplyDemand` use
case. Request includes industry, optional sub-industry, aggregate
region, explicit constituent scope, timezone-aware `as_of`, optional
explicit source, and required config. Use constructor-injected
repositories. The use case loads candidates, resolves
compatibility/ambiguity, calls pure Domain calculation, persists, and
returns DTO. It never commits. No ORM/session leakage into
Domain/Application.

## 10. Tests

### Domain

-   config validation;
-   flow gap/ratio;
-   exact prior-year shipment growth;
-   zero/negative denominators;
-   Decimal precision, rounding, overflow, DecimalException;
-   all phase branches and threshold edges;
-   missing evidence and contradictory evidence;
-   corroboration requirements;
-   immutable snapshot/provenance validation.

### Compatibility/PIT

-   source, industry/sub-industry, region, requested scope mismatch;
-   actual contributor region mismatch despite same requested scope;
-   coverage unknown/mismatch;
-   unit/currency/classification mismatch;
-   policy/calculation version mismatch;
-   period mismatch/duration mismatch;
-   future aggregate/contributor availability;
-   incomplete scope;
-   source ambiguity;
-   deterministic latest `(as_of,id)`.

### Inventory linkage

-   observation date equals flow period end;
-   exact production/shipments aggregate IDs referenced;
-   wrong input IDs excluded;
-   region/source/unit/currency mismatch excluded;
-   no nearest-date fallback;
-   missing inventory yields PARTIAL/UNKNOWN as appropriate.

### Persistence

-   real SQLite round trip of snapshot/scopes/inputs;
-   Decimal precision;
-   FK/check constraints;
-   append-only behavior;
-   rollback removes parent and children;
-   repository does not commit;
-   migration upgrade/downgrade preserves Sprint 15-18 data.

### Quality gates

pytest with coverage threshold, Ruff lint, Ruff format, mypy. Do not
weaken existing gates.

## 11. Definition of Done

-   Domain entities/config/service.
-   Repository contract and Infrastructure adapter.
-   Typed Application DTO/use case.
-   Additive migration.
-   No breaking changes to Sprint 15-18.
-   Unit, integration, PIT, compatibility, Decimal, migration, rollback
    tests.
-   Update Architecture, Database Design, Roadmap.
-   CI gates pass.
-   No unresolved P1/P2 review findings.

## 12. Design cautions

1.  Use Sprint 18 `input_references` to prove inventory was calculated
    from the exact flow aggregate IDs; date matching alone is
    insufficient.
2.  Include policy and calculation versions in Sprint 19 cohort
    signatures, even though Sprint 18's signature did not yet include
    them.
3.  Never infer constituent scope by traversing current Region Master
    relationships.
4.  Requested scope and actual contributor composition are different;
    compare both.
5.  Preserve the distinction between flow gap and physical inventory
    change.
6.  No empirical industry calibration exists; config is explicit and
    mandatory.
7.  Do not add Orders/Sales substitution in v1.
