# Roadmap

## Completed foundations

- Sprint 01: Project, domain, persistence, and quality-check foundation.
- Sprint 02: Provider-neutral market-data DTOs, CSV input adapter, and point-in-time market persistence.
- Sprint 03: Security, exchange, identifier, and listing normalization.
- Sprint 04: Point-in-time financial statement, item, mapping, and revision foundation.
- Sprint 05: Generic data-ingestion contracts, raw acquisition retention, run tracking, and mock end-to-end orchestration.
- Sprint 06: CSV `prices.daily` and `fx.daily` integration with shared DTOs and validation, existing repository idempotency, and normalized SAVEPOINT persistence.
- Sprint 07: Market-data quality reports, exchange trading sessions, configurable outlier candidates, append-only anomaly history, and source-scoped point-in-time revision review.
- Sprint 13: Append-only earnings Cycle Score v1 using PIT annual FY operating-profit history, configurable phase/scoring rules, coverage/confidence, and source/revision provenance.
- Sprint 14: Company-level annual inventory metrics, conservative configurable trend, PIT source/revision provenance, and append-only inventory snapshots.
- Sprint 15: Provider-neutral point, period, and event industry signal observations with append-only PIT persistence, source-scoped revisions, ingestion contracts, and explicit ambiguity handling.
- Sprint 18: Descriptive industry inventory cycle analysis over persisted PIT aggregates, with exact calendar YoY matching, production/shipments period diagnostics, versioned classification thresholds, explicit scope/source provenance, and append-only snapshots.

## Recommended next step

Further industry cycle analysis requires calibrated thresholds and sufficiently complete regional time series. Inventory engine v1 is descriptive only and does not infer supply-demand balance, capacity, or investment signals.

## Current boundary

Quality thresholds need market-specific calibration and review; corporate actions can produce legitimate extreme moves, and configured holiday calendars need maintenance. Cycle Score v1 only represents annual company operating-profit patterns, not a complete industry cycle. Industry inventory thresholds also need calibration and remain descriptive only. Industry signal taxonomy/region mapping and source adapters, additional inventory aggregation methods, other CSV datasets, live providers (including IBKR), automated scheduling, Cycle Score input extensions, and opportunity/screening/backtesting engines remain future work.

Sprint 16 establishes curated classification versions/mappings and an explicit
multi-parent region master. Live classification feeds, automated crosswalks,
company assignment, region aggregation, and graph-write concurrency coordination
remain future work.
# Sprint 12 — Value Score

Value Score v1 is implemented as an append-only point-in-time snapshot engine.
Cash flow scoring remains unavailable until operating cash flow and CAPEX are
part of the standardized financial input model. Peer selection remains explicit
and caller-supplied; automated peer discovery is out of scope.

Review hardening keeps source and PIT integrity failures fatal and records
submetric coverage explicitly so partial PER/PBR and normalized valuation data
contribute proportionally to overall coverage and score weighting.
