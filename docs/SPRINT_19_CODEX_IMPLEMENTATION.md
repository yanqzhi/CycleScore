# Codex Implementation Instructions --- Sprint 19

## Mission

Implement **Industry Supply & Demand Engine v1** in `yanqzhi/CycleScore`
strictly according to `docs/INDUSTRY_SUPPLY_DEMAND_ENGINE_SPEC.md`.

The engine consumes persisted Sprint 17
`IndustrySignalAggregateSnapshot` and Sprint 18
`IndustryInventorySnapshot` Domain entities. Do not re-aggregate raw
observations or duplicate Sprint 18 inventory calculations.

## Mandatory workflow

1.  Inspect `git status`; do not overwrite unrelated working-tree
    changes.
2.  Read the current code and docs, especially:
    -   `docs/ARCHITECTURE.md`
    -   `docs/DATABASE_DESIGN.md`
    -   `docs/INDUSTRY_SIGNAL_SPEC.md`
    -   `docs/INDUSTRY_SIGNAL_AGGREGATION_SPEC.md`
    -   `docs/INDUSTRY_INVENTORY_ENGINE_SPEC.md`
    -   `src/cyclescope/domain/entities/industry_signal_aggregate.py`
    -   `src/cyclescope/domain/entities/industry_inventory.py`
    -   `src/cyclescope/domain/services/industry_inventory.py`
    -   Sprint 17/18 Application use cases, DTOs, repository contracts,
        SQLAlchemy models/repositories, and tests.
3.  Inspect Alembic history and `alembic heads`. Use the actual current
    head as `down_revision`; do not assume migration 0026 is still the
    head.
4.  Implement incrementally, preserving the modular-monolith dependency
    direction. Domain must not import SQLAlchemy, pandas, providers, or
    filesystem APIs.
5.  Run the complete local test and quality suite available in the repo.
    Report exact commands and results; never claim tests passed unless
    actually executed.
6.  Review the final diff for unrelated changes, migration
    reversibility, and backward compatibility.
7.  Do not commit or push unless the user explicitly asks.

## Required implementation

### Domain

-   Add immutable config, phase/status enums, input-reference and
    snapshot entities.
-   Add a pure calculation service.
-   Use mandatory explicit Decimal thresholds; do not invent production
    defaults.
-   Implement exact flow-pair compatibility, flow gap, normalized gap
    ratio, exact-anniversary shipment YoY, and deterministic phase
    classification exactly as specified.
-   Use expanded Decimal local context; round half-even only at the
    output boundary; validate NUMERIC(38,12) overflow.
-   Preserve missing values as null with reasons.
-   Keep coverage, evidence coverage, and confidence separate.
    Confidence is null in v1.
-   A flow gap is not physical inventory change.

### Compatibility and PIT

-   Load persisted aggregate and inventory snapshots through existing
    repository contracts.
-   Apply PIT filtering before selecting latest snapshots.
-   Enforce `available_at <= as_of`; never use `collected_at` for
    visibility.
-   Require compatible source, industry/sub-industry, region, requested
    scope, actual contributor composition, unit/currency, classification
    references, policy version, and calculation version.
-   Require exact matching production/shipments periods.
-   Require exact prior-year anniversary and identical period duration
    for shipment YoY.
-   Inventory observation date must equal flow period end, and inventory
    input references must point to the exact production/shipments
    aggregate IDs used.
-   Reject ambiguous multi-source cohorts unless source is explicitly
    selected.
-   Do not traverse Region Master to infer constituents.
-   Retain excluded candidates and reasons.

### Application

-   Add typed request/response DTOs.
-   Require `target_period_end` in the analysis request and select only
    the exact requested period; never fall back to a different latest
    period. Persist a clear unavailable result when no exact pair exists.
-   Add `AnalyzeIndustrySupplyDemand` using constructor-injected
    repositories.
-   Application coordinates reads, cohort selection, Domain calculation,
    and persistence.
-   No ORM/session leakage into Domain/Application.
-   No implicit commit.

### Infrastructure

-   Add SQLAlchemy snapshot/input/scope models and repository adapter.
-   Add an additive Alembic migration using the actual current head.
-   Persist input references, requested scope, actual contributing
    regions, coverage, config, and exclusion/unavailable reasons.
-   Repository uses `flush()` only; caller owns transaction.
-   Preserve Sprint 15-18 tables/data/APIs. Do not edit old migrations.

### Tests

Add unit and real-SQLite integration tests for: - actual region
composition mismatch; - requested scope mismatch; -
source/unit/currency/classification mismatch; - policy/calculation
version mismatch; - PIT future-availability exclusion; - exact
prior-year date and period matching; - zero/negative denominators; -
inventory linkage to exact flow aggregate IDs; - Decimal
overflow/rounding; - deterministic latest snapshot selection; - source
ambiguity; - append-only persistence and rollback; - migration
upgrade/downgrade.

Follow every additional test case in the specification.

## Classification guardrails

Follow the exact precedence and boundary operators in the specification.
Do not reduce classification to a sign check. Oversupply and undersupply
require corroborating evidence; a large production/shipments gap alone
is insufficient. Do not infer direction from missing values. Do not
introduce hidden score weights, guessed thresholds, Orders/Sales
fallback, or confidence formulas. Keep raw expanded-precision Decimal
ratios and growth values for classification comparisons; round only the
values persisted in the final snapshot, with NUMERIC overflow checked at
that boundary.

## Documentation

Update: - `docs/ARCHITECTURE.md` - `docs/DATABASE_DESIGN.md` -
`docs/ROADMAP.md` - `docs/INDUSTRY_SUPPLY_DEMAND_ENGINE_SPEC.md`

State clearly that v1 is descriptive and not an investment signal.

## Completion report

When implementation is complete, report: 1. final commit SHA only if the
user's workflow created a commit; 2. changed files grouped by
Domain/Application/Infrastructure/Migrations/Tests/Docs; 3. migration
revision and parent revision; 4. exact test/quality commands and
results; 5. known limitations and unresolved P1/P2 findings; 6.
confirmation that Sprint 15-18 behavior and migrations were not altered.

Do not mark Sprint 19 complete while P1/P2 findings remain or CI quality
gates fail.
