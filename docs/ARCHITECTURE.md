# Architecture

CycleScope is a modular monolith packaged under `src/cyclescope`.

- `domain` contains framework-independent company, security, exchange, identifier, listing, exposure, and market-data entities, value objects, validation exceptions, and repository contracts.
- `application` contains typed company/security/exchange/listing/identifier/exposure use cases, shared exposure validation, market-data import/retrieval use cases, DTOs, and provider ports.
- `infrastructure/config` loads validated Pydantic Settings. `infrastructure/logging` configures standard-library console and rotating-file handlers.
- `infrastructure/database` contains SQLAlchemy mappings, engine/session setup, Alembic migrations, and master-data and market-data repository adapters.
- `infrastructure/market_data` contains input adapters, including the CSV adapter. Providers implement Application acquisition ports and map their source data into common DTOs without changing domain entities or use cases.
- `engines` and `presentation` are placeholders for later sprints.

Dependencies point inward: adapters depend on domain contracts, while domain types do not import database, UI, data-frame, or provider libraries. Session and engine factories are passed explicitly. Repository contracts use concrete domain entity types, and adapters explicitly map between SQLAlchemy rows and those entities. ORM models and persistence mappings stay inside Infrastructure.

Company industry revenue shares are individually constrained to `[0, 1]` in the database and domain. The application validates aggregate shares across all time-overlapping exposures for one company, requiring their total to be at most `1` on every date. This cross-row rule is not expressed as a database constraint because arbitrary time intervals cannot be safely enforced by a simple row check.

Company is the issuer; Security is the financial instrument/share class; Listing owns exchange-specific tickers, trading currencies, listing dates, and status. Exchange is a stable venue reference identified by a unique exchange code. One Security may have multiple Listings. Security identifiers are typed text records whose global or exchange scope is resolved by one Domain rule; overlapping reuse is rejected in Application. Status transitions are stored as append-only listing status events, while the listing keeps its current status. Migration 0004 maps recognized legacy listings and retains unmappable source fields for reconciliation while preserving Security IDs.

Application use cases own identifier, listing interval, and exposure aggregate rules. SQLite race-sensitive write units should use Infrastructure's `transaction(session_factory)`, which reserves the single writer with `BEGIN IMMEDIATE` before checks. For PostgreSQL, repository adapters can add advisory locks for natural-key scopes, Company row locks for exposure edits, and range exclusion constraints without moving validation into Presentation.

SQLite is the initial local store. SQLAlchemy types and Alembic migrations keep the schema portable to PostgreSQL, subject to normal migration review.

Market-data use cases receive provider and repository implementations through constructor injection. Providers receive `HistoricalPriceRequest` or `FxRateRequest` and return `RawDailyPriceRecord` or `RawFxRateRecord`; these DTOs contain typed dates, decimals, and integer volume, with row-level parsing errors where needed. Use cases own shared Domain validation, duplicate handling, provenance, and persistence. The CSV adapter alone accepts file paths and translates CSV cells into the common DTOs. A future IBKR adapter can translate its API response into the same DTOs and implement the same ports; no CSV behavior is part of that contract. Domain prices and rates retain source, observation date, publication date, availability time, collection time, and revision number. Stored observations are append-only: corrections are new revisions. `MarketDataAccess` provides typed price/FX reads for latest-by-source, periods, preceding observations, revisions, and date-specific as-of queries. Every read uses an explicit point-in-time cutoff, preserves source separation, and delegates SQL-level eligible-revision selection to the repository contract. See [MARKET_DATA_SPEC.md](MARKET_DATA_SPEC.md) for details.

### Financial statement foundation

Application use cases accept common financial statement input DTOs and typed Domain entities. The Infrastructure repositories map these entities to SQLAlchemy rows. No source-specific document format or live provider is part of Sprint 04. Historical revisions are immutable; the caller owns the transaction, including rollback on any line persistence failure. See [FINANCIAL_DATA_SPEC.md](FINANCIAL_DATA_SPEC.md).

### Valuation calculations

Valuation calculations use shared point-in-time price and statement access, then calculate with Domain `ValuationInputs`. Quarterly EPS is not summed; the assembler prefers a reported FY/TTM EPS or supplies aligned TTM net income and weighted-average shares for derivation. Each metric snapshot retains only the input-line and price references used by its formula. Snapshot history remains append-only and transaction ownership stays with the caller. See [VALUATION_SPEC.md](VALUATION_SPEC.md).

### Normalized earnings foundation

`CalculateNormalizedEarnings` assembles source-scoped annual FY records through `GetFinancialStatements`, then delegates to a pure Domain analyzer. It computes historical statistics, coverage, confidence, and historical peak/trough candidates without using data unavailable at the requested cutoff. Normalized PER and EV/EBITDA reuse the existing valuation calculator. Infrastructure stores results and FK-backed source references append-only in migration `0013`; the caller owns commit and rollback. See [NORMALIZED_EARNINGS_SPEC.md](NORMALIZED_EARNINGS_SPEC.md).

### Generic ingestion pipeline

`ExecuteDataIngestionPipeline` coordinates acquisition, raw retention, transformation, validation, and idempotent normalized persistence. Its request contains source and dataset identity plus scalar parameters; it does not carry a file path. For `prices.daily` and `fx.daily`, Infrastructure's `CsvMarketDataAdapter` reads configured files and persists their original bytes, and `CsvMarketDataTransformer` uses the existing CSV parser to produce shared market-data row DTOs. Application contexts carry the security/pair, source, and provenance needed for Domain construction. Dataset validators call the shared `daily_price_from_record` and `fx_rate_from_record` functions also used by the legacy import use cases. Normalized adapters use the existing market repositories and natural revision keys inside a SAVEPOINT. Run and raw repositories stay caller-transaction-bound, and the pipeline never commits. Future API or IBKR adapters can return the same raw batch format and common DTOs without CSV or filesystem dependencies. See [DATA_PIPELINE_SPEC.md](DATA_PIPELINE_SPEC.md).

### Market-data quality and revision review

Application's `MarketDataQualityAssessor` accepts Domain `DailyPrice`/`FxRate` records and a `TradingCalendar` port. It computes expected-session coverage, duplicate and cross-source consistency checks, configurable movement and rolling-volume outlier candidates, versioned component scores, and anomaly explanations. Missing calendar configuration is represented as unknown input; unexpected calendar failures propagate. Quality workflows query the full report period and at most 20 preceding eligible observations per source, keeping lookback rows out of report coverage and counts. SQLAlchemy stores immutable report snapshots and anomaly detection events. `transition_anomaly` is the supported status-change operation and writes a lifecycle event atomically with the state update; optimistic versioning rejects stale concurrent writes. Revision management uses existing append-only repositories, requires a source ID, and selects only records satisfying `available_at <= as_of`. Assessment and retrieval never change market data. See [MARKET_DATA_SPEC.md](MARKET_DATA_SPEC.md) and [ENGINE_SPEC.md](ENGINE_SPEC.md).

### Valuation data foundation

`BuildValuationInputs` composes the existing `GetFinancialStatements` and `MarketDataAccess` use cases and maps standardized `FinancialItem` rows into validated Domain inputs. A single aware cutoff controls both repositories; source and revision provenance is preserved. Domain services calculate versioned PER, PBR, EPS, BVPS, market capitalization, enterprise value, EBITDA, and EV/EBITDA from Decimal values. Historical snapshots use SQLAlchemy adapters and an additive migration; line-level source references have foreign keys and publication/availability metadata. Application has typed input and historical snapshot query DTOs. See [VALUATION_SPEC.md](VALUATION_SPEC.md). No scoring or ranking engine is included.
