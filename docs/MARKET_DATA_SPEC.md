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

The repository returns the highest eligible revision per observation date and source. When the application returns one series without a `source_id` filter, it selects one source per observation date by greatest `available_at`, then greatest revision number, then lowest source ID. Supplying a `source_id` selects that source specifically. Results are chronological.

## Provider boundary

Application defines `HistoricalPriceProvider` and `FxRateProvider` protocols over typed raw-row DTOs. `CsvHistoricalMarketDataProvider` implements them without pandas or external APIs. A future IBKR adapter belongs under Infrastructure and should translate IBKR responses into these same raw DTOs; Domain and Application must remain provider-neutral.

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

Each row is normalized and validated before persistence. Missing required cells, invalid dates or numbers, invalid currency codes, negative volume, invalid OHLC relationships, invalid FX pairs/rates, and domain validation failures are returned as `ValidationIssue(row_number, message)` entries. An invalid header is a file-level `CsvFormatError`. A valid row with an already stored revision key is reported as skipped duplicate.

`PriceImportSummary` and `FxImportSummary` include total, imported, duplicate, rejected counts, validation errors, and imported domain observations. The use cases flush inserts through repository ports but do not commit a transaction; the caller owns transaction scope and can roll back the batch.

## Current limitations

The CSV import is invoked from Python use cases; there is no ingestion CLI, scheduling, live provider, corporate-action adjustment, exchange calendar, or source-priority configuration. When no source is requested, source choice follows the deterministic rule above and may not match a future business preference. Imported revision numbering and `available_at` are trusted metadata supplied by the caller.
