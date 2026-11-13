# Database design

All tables use integer primary keys and UTC `created_at` / `updated_at` timestamps. Dates representing listings or exposure validity use SQL `DATE`; revenue shares use `NUMERIC(8, 7)` and are constrained to `[0, 1]`.

| Table | Purpose and constraints |
| --- | --- |
| `industries` | Unique code; active flag. |
| `sub_industries` | Required industry FK (`RESTRICT`); unique code within an industry. |
| `companies` | Issuer master data; indexed country code. |
| `securities` | Required company FK (`RESTRICT`); unique exchange/ticker pair; listing dates. |
| `company_industry_exposures` | Company and sub-industry FKs (`RESTRICT`), optional source FK (`SET NULL`), share and date-range checks. Supports multiple and historical exposures. |
| `data_sources` | Provider metadata only; no API credentials. Unique code. |
| `daily_prices` | Security and source FKs (`RESTRICT`); decimal OHLC and adjusted close; integer volume; observation/publication dates; availability and collection timestamps; revision. Unique security/date/source/revision. |
| `fx_rates` | Source FK (`RESTRICT`); decimal quote-per-base rate; currency pair; observation/publication dates; availability and collection timestamps; revision. Unique pair/date/source/revision. |

SQLite foreign-key enforcement is enabled on every connection. Alembic owns schema changes; initialization upgrades to `head` and inserts missing initial industries without overwriting existing rows. No market time-series tables are included in Sprint 01.

The application validates that each company's revenue shares across all time-overlapping exposure records sum to no more than `1`. The validator must receive the complete company exposure set, including proposed changes. This aggregate rule is deliberately application-level; the schema retains only per-record range and date-order checks.

Market data was added by migration `0002_market_data`; migration `0001_master_data` was not changed. Daily price values use `NUMERIC(20, 8)`, FX rates use `NUMERIC(24, 12)`, and volume uses `BIGINT`. Database checks reject negative prices/volume, invalid OHLC relationships, non-positive FX rates, identical FX currencies, and non-positive revisions. Zero stock prices are permitted. Market observation dates are exchange-local `DATE` values; timestamps are stored as UTC-aware datetimes. See [MARKET_DATA_SPEC.md](MARKET_DATA_SPEC.md) for query and revision policy.
