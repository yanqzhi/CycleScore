# Roadmap

## Completed foundations

- Sprint 01: Project, domain, persistence, and quality-check foundation.
- Sprint 02: Provider-neutral market-data DTOs, CSV input adapter, and point-in-time market persistence.
- Sprint 03: Security, exchange, identifier, and listing normalization.
- Sprint 04: Point-in-time financial statement, item, mapping, and revision foundation.
- Sprint 05: Generic data-ingestion contracts, raw acquisition retention, run tracking, and mock end-to-end orchestration.

## Recommended next step

Connect the generic pipeline to one existing dataset in a narrow follow-up, preferably the CSV market-data adapter. Reuse existing price/FX validation and repository natural keys; verify raw replay, retry idempotency, and caller-owned transaction behavior. Keep live providers, scheduling, parallel workers, financial taxonomy automation, and analytical engines in later work.

## Current boundary

Sprint 05 provides mock adapters only. It does not replace current market-data or financial-data use cases and does not establish a production provider or dataset-specific normalized persistence adapter.
