# Company and security master specification

## Entities and relationships

- **Company** is the issuer or underlying legal/business entity. It has no ticker uniqueness rule and may issue multiple securities.
- **Security** is an instrument or share class issued by a company. Security type distinguishes common stock, preferred stock, depositary receipts, and other instruments. The existing `ticker` and `exchange` columns remain for compatibility with earlier releases; normalized exchange-specific symbols belong to Listings.
- **Exchange** is a stable venue reference, independent of company symbols. `exchange_code` is the unique natural/stable code; the integer `exchange_id` is the local database key. Region, IANA timezone, country, and trading currency are reference data and are not hardcoded into Domain rules.
- **SecurityIdentifier** records an explicit identifier type and a text value. Exchange scope is optional: global identifiers such as ISIN can be unscoped while trading symbols and venue-local codes can reference an Exchange. Validity dates preserve identifier changes. Identifiers are not mandatory or assumed to exist for every security.
- **Listing** joins a Security to an Exchange with a ticker, trading currency, listing date, optional delisting date, and current status. A security may have listings on multiple exchanges. Listing status changes are retained as append-only `ListingStatusEvent` rows.

The schema accommodates Japan (for example `XTKS`, `Asia/Tokyo`, `JPY`), the United States (`XNYS`/`XNAS`, `America/New_York`, `USD`), Mainland China (`XSHG`/`XSHE`, `Asia/Shanghai`, `CNY`), and Hong Kong (`XHKG`, `Asia/Hong_Kong`, `HKD`). These are suggested reference codes, not a closed enum; callers can register other venues without changing Domain code.

## Effective dates and integrity

Listing and identifier date ranges are inclusive. A delisting date must be on or after the listing date. A `delisted` Listing requires a delisting date; active or suspended listings do not have one. Status events must move forward in time, and delisted listings are terminal. Transition updates and their status event insert run in the caller-owned database transaction.

Identifier reuse is scoped by identifier type, text value, and optional exchange. Application checks reject overlapping validity periods for a value already assigned in the same scope. Listing ticker reuse is scoped by Exchange and checked for overlapping listing/delisting dates. These interval-overlap rules remain application-level because a portable row-level unique or check constraint cannot express arbitrary interval exclusion in SQLite. Database constraints still enforce foreign keys, required fields, status values, and valid date ordering.

## Industry exposures

Each company exposure has a Decimal revenue share in `[0, 1]`. `RegisterCompanyIndustryExposure` and `UpdateCompanyIndustryExposure` load the complete company exposure set, apply the shared `validate_company_exposures` sweep, and persist only after aggregate validation passes. Non-overlapping intervals may independently have shares totaling up to 100%; every point in overlapping intervals must total at most 100%.

## Transaction and migration policy

Use cases flush through Domain repository interfaces and do not commit. The caller owns transaction boundaries so persistence failures roll back the aggregate operation. Migration `0003_multimarket_master_data` is additive, leaves `0001_master_data` and `0002_market_data` unchanged, and does not rewrite existing rows. No external security-master or exchange discovery provider is included.
