# Roadmap

## Completed foundations

- Sprint 01: Project, domain, persistence, and quality-check foundation.
- Sprint 02: Provider-neutral market-data DTOs, CSV input adapter, and point-in-time market persistence.
- Sprint 03: Security, exchange, identifier, and listing normalization.
- Sprint 04: Point-in-time financial statement, item, mapping, and revision foundation.
- Sprint 05: Generic data-ingestion contracts, raw acquisition retention, run tracking, and mock end-to-end orchestration.
- Sprint 06: CSV `prices.daily` and `fx.daily` integration with shared DTOs and validation, existing repository idempotency, and normalized SAVEPOINT persistence.

## Recommended next step

Add a dedicated raw replay workflow and decide whether financial statement imports need the same pipeline. Keep live providers, scheduling, parallel workers, taxonomy automation, and analytical engines in later work.

## Current boundary

Sprint 06 adds CSV only for daily prices and FX. Other CSV datasets, financial statement integration, live providers (including IBKR), and automated scheduling remain out of scope.
