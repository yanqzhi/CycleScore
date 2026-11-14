# Database design

All tables use integer primary keys and UTC `created_at` / `updated_at` timestamps. Dates representing listings or exposure validity use SQL `DATE`; revenue shares use `NUMERIC(8, 7)` and are constrained to `[0, 1]`.

| Table | Purpose and constraints |
| --- | --- |
| `industries` | Unique code; active flag. |
| `sub_industries` | Required industry FK (`RESTRICT`); unique code within an industry. |
| `companies` | Issuer master data; indexed country code. |
| `securities` | Required company FK (`RESTRICT`); instrument/share-class data only. Legacy listing columns are removed by migration 0004 after normalization. |
| `exchanges` | Stable exchange code, display name, country, market region, timezone, currency, active flag. |
| `security_identifiers` | Typed text identifiers with optional exchange scope, validity dates, and security/exchange FKs. Application rejects overlapping reuse in the same scope. |
| `listings` | Security/exchange FKs, ticker, trading currency, listing and delisting dates, current status. Ticker reuse is validated by overlapping effective dates in Application. |
| `listing_status_events` | Append-only listing status transitions keyed by effective date. |
| `legacy_listing_reconciliation` | Original legacy listing fields and a reason for rows that cannot be safely mapped to an Exchange/Listing. Unique per Security. |
| `company_industry_exposures` | Company and sub-industry FKs (`RESTRICT`), optional source FK (`SET NULL`), share and date-range checks. Supports multiple and historical exposures. |
| `data_sources` | Provider metadata only; no API credentials. Unique code. |
| `daily_prices` | Security and source FKs (`RESTRICT`); decimal OHLC and adjusted close; integer volume; observation/publication dates; availability and collection timestamps; revision. Unique security/date/source/revision. |
| `fx_rates` | Source FK (`RESTRICT`); decimal quote-per-base rate; currency pair; observation/publication dates; availability and collection timestamps; revision. Unique pair/date/source/revision. |

SQLite foreign-key enforcement is enabled on every connection. Alembic owns schema changes; initialization upgrades to `head` and inserts missing initial industries without overwriting existing rows. No market time-series tables are included in Sprint 01.

The application validates that each company's revenue shares across all time-overlapping exposure records sum to no more than `1`. The validator must receive the complete company exposure set, including proposed changes. This aggregate rule is deliberately application-level; the schema retains only per-record range and date-order checks.

Market data was added by migration `0002_market_data`; multi-market reference data by `0003_multimarket_master_data`; and Security/Listing normalization by `0004_security_listing_normalization`. Migrations `0001_master_data`, `0002_market_data`, and `0003_multimarket_master_data` are preserved. All existing Security IDs remain stable and market-data foreign keys continue to target `securities.id`. Recognized legacy listings move to Listing rows; unmappable rows are retained in `legacy_listing_reconciliation`; legacy listing columns and the old Security ticker uniqueness are then removed. Daily price values use `NUMERIC(20, 8)`, FX rates use `NUMERIC(24, 12)`, and volume uses `BIGINT`. Database checks reject negative prices/volume, invalid OHLC relationships, non-positive FX rates, identical FX currencies, and non-positive revisions. Zero stock prices are permitted. Market observation dates and listing lifecycle dates use `DATE`; timestamps are stored as UTC-aware datetimes. SQLite foreign keys are enabled during normal application use. Alembic temporarily disables them only around SQLite table rebuilds, then re-enables and runs `foreign_key_check`. See [MARKET_DATA_SPEC.md](MARKET_DATA_SPEC.md) for query and revision policy and [MASTER_DATA_SPEC.md](MASTER_DATA_SPEC.md) for master-data semantics and concurrency rules.
## Financial data foundation

Migration `0005_financial_data_foundation` adds provider-neutral statement, standardized item, statement line, and source mapping tables. Statements are append-only revisions partitioned by company, period, standard, consolidation scope, and source. `available_at` controls historical visibility; sources remain separate in every query. Financial line values use `NUMERIC(38, 12)` to support large issuer totals and fractional per-share/ratio-like observations without using binary floats; values outside this fixed precision must be rejected before persistence.

Migration `0007_ingestion_pipeline` adds `raw_data_records` and `ingestion_runs`. Raw events have a surrogate key and non-unique checksum index: repeated identical acquisitions remain separate events. Normalized idempotency continues to use each dataset's natural keys and source-specific revision semantics. Run rows reference raw records with RESTRICT semantics and retain lifecycle status, timestamps, metrics, and errors. The Application boundary enforces the configurable payload byte limit.

Migration `0008_market_data_quality` adds `data_quality_reports` and `data_anomalies`. Reports store scope, range, UTC as-of time, expected/available/missing sessions, coverage, first/last available dates, scoring version and configuration snapshot, component explanations, severity counts, score, and status. JSON stores typed component detail without copying price/rate rows. Anomaly records preserve an observation natural key and may link to its existing price or FX row; they also store detection rule/version, severity, detected/expected values, and lifecycle state. Report and anomalies persist atomically inside one SAVEPOINT; the caller owns commit/rollback. Existing market-data tables and revisions are unchanged.
