# Market data specification

## Domain model

`DailyPrice` represents an immutable OHLCV observation for one security, source, observation date, and revision. Prices use `Decimal`; volume is a non-negative integer. Prices must be finite and non-negative. High must be at least open, close, and low; low must not exceed open or close. Zero prices are allowed because a provider may report zero for a suspended, distressed, or otherwise exceptional instrument; missing values are rejected instead of converted to zero.

`FxRate` represents a positive finite `Decimal` quoted as units of quote currency per one unit of base currency. `CurrencyPair` validates distinct three-letter uppercase codes. This validates code shape, not membership against an ISO registry.

`MarketDataPeriod` is an inclusive range of exchange-local observation dates. Observation dates and publication dates are `DATE` values. `available_at`, `collected_at`, `created_at`, and `updated_at` are timezone-aware UTC timestamps. `publication_date` is retained separately from the exact `available_at` timestamp.

## Persistence and revisions

The additive Alembic revision `0002_market_data` creates `daily_prices` and `fx_rates`. A revision's uniqueness key includes the subject/pair, observation date, source ID, and revision number. Foreign keys point to `securities` and `data_sources` with `RESTRICT` deletion behavior.

Market observations are append-only. Importing a key that already exists increments the duplicate count and leaves the original row untouched. Corrections must be sent with a higher revision number; earlier revisions remain stored and can be retrieved with the repository's `get_revisions` operation or by an earlier point-in-time cutoff. The revision number is provided by the caller because provider-specific revision numbering or correction detection is not inferred.

## Availability and source selection

Historical queries require an aware `as_of` timestamp. Rows with `available_at > as_of` are excluded. They also exclude observation dates after the UTC calendar date of `as_of`; this conservative rule prevents future observations when exchange timezone metadata is not yet part of the security master.

The repository returns the highest eligible revision per observation date and source. Queries without a `source_id` filter preserve one row for every source; they never merge or silently choose a preferred source. Supplying a `source_id` restricts results to that source. Results are chronological, with source ID as the deterministic secondary order.

## Unified point-in-time access

Application's `MarketDataAccess` facade exposes analogous typed queries for prices and FX: latest observations per source, inclusive period reads, preceding observations, date-specific as-of reads, and source-scoped revision history. Query DTOs validate positive IDs, date ranges, minimum counts, and aware cutoffs, then normalize cutoffs to UTC. Query responses carry the requested UTC `as_of`; observation entities provide date, source, revision, `available_at`, `collected_at`, and currency/pair without duplicating those fields in the wrapper.

Every query excludes `available_at > as_of` and observation dates after the UTC date of `as_of`. Revisions are ranked within `(observation_date, source_id)` after the availability filter; the highest eligible revision wins, with availability timestamp and row ID as deterministic ties. `collected_at` never controls visibility. Revision-history requests require a source ID and return only revisions available at the requested cutoff. A date-specific query without a source returns one eligible revision for each source.

Period responses include per-source retrieval summaries: latest eligible observation date and availability timestamp, number of selected observations in the requested period, and whether the period has data. `AVAILABLE` means the requested minimum observation count was met; `INSUFFICIENT_DATA` means some observations exist but the request's explicit minimum was not met; `NO_DATA` means no eligible observation exists in that period. These labels describe query results, not source health. If a source is explicitly selected but has no matching rows, the response still identifies that source with `NO_DATA`.

Repositories use SQL window functions to rank eligible revisions before returning rows, avoiding materializing every revision in Python. The bounded preceding query returns at most the requested number of latest observations per source. Migration `0011_market_data_access_indexes` adds source-scoped indexes that include observation date, `available_at`, and revision number for price and FX queries; it retains the existing broader date indexes for unfiltered-source period reads.

## Provider boundary

Application defines `HistoricalPriceProvider.fetch_historical_prices(HistoricalPriceRequest)` and `FxRateProvider.fetch_fx_rates(FxRateRequest)`. Both return shared `RawDailyPriceRecord` / `RawFxRateRecord` DTOs containing typed `date`, `Decimal`, `int`, and `str` values plus row-level parsing errors. The request DTOs describe security/currency and optional date bounds; neither requests nor provider protocols contain file paths.

`CsvHistoricalMarketDataProvider` is an Infrastructure input adapter configured with CSV paths. It reads the documented CSV format, parses cells, and returns common DTOs. It does not own business validation. Application use cases apply the same Domain validation, duplicate detection, revision/provenance handling, and repository persistence regardless of provider. A future IBKR adapter can acquire data from its API and map the response to the same common DTOs; it will not need to implement CSV behavior. Live IBKR connectivity is not included.

## CSV format

Price file required columns:

```csv
date,open,high,low,close,volume
2024-01-02,10.25,11.00,10.00,10.75,120000
```

Optional price columns are `adjusted_close` and `publication_date`. Currency, security ID, source ID, `available_at`, `collected_at`, and revision number are supplied as import metadata, not repeated on each row.

FX file required columns:

```csv
base_currency,quote_currency,date,rate
USD,JPY,2024-01-02,145.25
```

Optional FX column: `publication_date`. The file reader accepts UTF-8 (with or without BOM), trims cells, and requires the exact documented header names. Dates use ISO `YYYY-MM-DD`; numbers use dot-decimal notation without locale grouping.

## Validation and import summaries

CSV syntax and primitive conversion happens in the CSV adapter. Parse failures are carried with their source row in the common DTO and surfaced as `ValidationIssue(row_number, message)`. Shared Application/Domain validation handles missing required values, invalid currency codes, negative volume, invalid OHLC relationships, invalid FX pairs/rates, and domain validation failures. An invalid header is a file-level `CsvFormatError`. A valid row with an already stored revision key is reported as skipped duplicate.

`PriceImportSummary` and `FxImportSummary` include total, imported, duplicate, rejected counts, validation errors, and imported domain observations. The use cases flush inserts through repository ports but do not commit a transaction; the caller owns transaction scope and can roll back the batch.

## Current limitations

The CSV adapter is invoked from Python application wiring; there is no ingestion CLI, scheduling, live provider, corporate-action adjustment, exchange calendar, or source-priority configuration. When no source is requested, source choice follows the deterministic rule above and may not match a future business preference. Imported revision numbering and `available_at` are trusted metadata supplied by the caller.
# Pipeline import path

The generic ingestion pipeline supports CSV imports for `prices.daily` and `fx.daily`. It preserves the original CSV bytes in the raw-data table, then parses into the same provider-independent row DTOs used by direct imports. The price/FX validation and normalized persistence rules are shared with existing import use cases; duplicate natural keys are skipped and a later correction must use a new revision. Pipeline imports keep caller-owned transaction semantics, with normalized rows protected by a SAVEPOINT. CSV paths and parsing remain Infrastructure concerns. Future IBKR or API adapters will provide acquired bytes and common normalized records without implementing a CSV interface. See [DATA_PIPELINE_SPEC.md](DATA_PIPELINE_SPEC.md).
# Quality reports, anomalies, and revisions

`AssessDailyPriceQuality` and `AssessFxRateQuality` read existing Domain entities through the append-only market repositories, filter by source and `available_at <= as_of`, and persist a typed `DataQualityReport` with its anomaly candidates. Quality never repairs, deletes, or revises observations. Structural rules (Decimal/date/currency/positive-rate/OHLC/revision checks) remain owned by the Domain entities and database foreign keys/checks; the quality workflow does not duplicate them.

## Trading-session coverage

The Application `TradingCalendar` port supplies expected sessions for `EXCHANGE:<exchange_id>` or the configured `FX` calendar. Infrastructure's `WeekdayTradingCalendar` excludes Saturday/Sunday and configured holiday dates. Deployments must map each security to a known exchange and configure that calendar. An absent calendar object or an unregistered exchange/FX calendar returns `INSUFFICIENT_DATA` with `calendar_status=UNKNOWN_CALENDAR`, no coverage denominator or numeric score, and no missing-session anomalies. Only the explicit not-configured result is treated this way; unexpected calendar errors propagate. Zero expected sessions are `NOT_APPLICABLE`, never a divide-by-zero result. Coverage is expected sessions with available observations divided by expected sessions, expressed as percent. First/last observed dates are reported separately.

## Quality score and configurable outliers

Versioned `DataQualityConfig` defaults to these weighted components: completeness 30%, structural validity 25%, consistency 20%, outlier assessment 15%, and provenance 10%. Each component score and explanation is saved. The final score is the sum of `component_score × weight`, from 0 through 100. Unknown calendar, zero expected sessions, or no observations make required inputs unavailable; those reports do not receive a numeric score. Scoring configuration version, thresholds, and weights are snapshotted on every report.

The five component names must each appear once in the configuration; unknown, missing, duplicate, negative, non-finite, or non-normalized weights are rejected. The exact validated weights are used both for scoring and saved in the report snapshot. An unavailable component keeps its configured weight and a null score; the other weights are not redistributed, and the overall score is unavailable.

Default candidate thresholds are an absolute daily close move above 20% for prices, above 5% for FX, and volume greater than five times the median of up to 20 preceding records when at least five historical records exist. Quality workflows retrieve the 20 most recent eligible prior observations per source plus every report-period observation. Repository selection first applies `available_at <= as_of`, then selects the highest eligible revision per source/date. Prior observations provide movement and rolling-volume baselines, but do not affect report coverage, available-record counts, report dates, or anomaly counts. Future-dated and not-yet-available rows are excluded. A numeric price quality score requires six distinct observations per source (so volume history can be assessed); FX scores require at least two. Below those minimums the outlier component is unavailable and the report is `INSUFFICIENT_DATA`, not a perfect score. Values exceeding twice the movement threshold receive CRITICAL severity; other threshold breaches receive ERROR for movement and WARNING for volume. These are review candidates, not errors proven by the source. Corporate actions, splits, dividends, and market structure can explain large changes. Outlier detection never auto-corrects data. The Domain already rejects invalid OHLC relationships; those records cannot enter normalized repositories through supported imports.

Duplicate natural keys are distinguished as exact or conflicting at the CSV validation boundary, before persistence; the rejected row retains its source row number and the import source remains on the run. The current persisted-key check still returns a duplicate count without loading the stored row to compare its values, so classifying conflicts against earlier imports is a follow-up for a repository lookup/result contract. Different sources remain separate; differing values for the same date are reported as potential cross-source conflicts, not merged. Database uniqueness and revision semantics are unchanged, existing rows are never overwritten, and duplicates already in storage are reported by quality assessment. Missing-session anomalies are generated only from configured expected sessions. Anomaly records are append-preserved for each assessment. Status changes are supported through `transition_anomaly`, which updates the anomaly and appends exactly one lifecycle event with prior/new status, time, and nullable actor in the same caller-owned transaction. The legacy `update_anomaly` method rejects status changes. SQLAlchemy optimistic versioning prevents stale concurrent writes; a losing transition fails without retaining its audit event. Terminal outcomes record `resolved_at` and cannot be changed. Detection rule and version are stored with severity and explanation.

## Revision selection

`MarketDataRevisionManagement` requires an explicit source ID to inspect all revisions for an observation. As-of selection first excludes every row with `available_at > as_of`, then deterministically chooses the highest eligible revision number (availability and row ID break ties). `collected_at` and ingestion `fetched_at` never substitute for `available_at`. Revision comparison returns changed fields for records sharing the same source-scoped natural key. A later correction does not alter earlier rows or historical as-of results.

## Limitations

The calendar implementation supports weekdays and manually configured holidays; it does not model exchange half-days, emergency closures, daylight-saving session times, FX holiday conventions, or a live calendar feed. Thresholds need asset- and venue-specific calibration. Statistical checks are intentionally simple and do not adjust for corporate actions. Data-quality scores are independent of Value Score, Cycle Score, and Opportunity Score. Persistence is local SQLite/SQLAlchemy; no engine consumes these reports yet.
