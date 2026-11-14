# Roadmap

## Completed foundations

- Sprint 01: Project, domain, persistence, and quality-check foundation.
- Sprint 02: Provider-neutral market-data DTOs, CSV input adapter, and point-in-time market persistence.
- Sprint 03: Security, exchange, identifier, and listing normalization.
- Sprint 04: Point-in-time financial statement, item, mapping, and revision foundation.
- Sprint 05: Generic data-ingestion contracts, raw acquisition retention, run tracking, and mock end-to-end orchestration.
- Sprint 06: CSV `prices.daily` and `fx.daily` integration with shared DTOs and validation, existing repository idempotency, and normalized SAVEPOINT persistence.
- Sprint 07: Market-data quality reports, exchange trading sessions, configurable outlier candidates, append-only anomaly history, and source-scoped point-in-time revision review.

## Recommended next step

Add raw replay workflows and decide whether financial statement imports need the same pipeline. Keep live providers, scheduling, parallel workers, taxonomy automation, and analytical engines in later work.

## Current boundary

Quality thresholds need market-specific calibration and review; corporate actions can produce legitimate extreme moves, and configured holiday calendars need maintenance. Other CSV datasets, financial statement integration, live providers (including IBKR), automated scheduling, and analytical engines remain out of scope.
