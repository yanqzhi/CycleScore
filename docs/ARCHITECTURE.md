# Architecture

CycleScope is a modular monolith packaged under `src/cyclescope`.

- `domain` contains framework-independent master-data and market-data entities, value objects, validation exceptions, and repository contracts.
- `application` contains exposure validation, market-data import/retrieval use cases, typed DTOs, and provider ports.
- `infrastructure/config` loads validated Pydantic Settings. `infrastructure/logging` configures standard-library console and rotating-file handlers.
- `infrastructure/database` contains SQLAlchemy mappings, engine/session setup, Alembic migrations, and master-data and market-data repository adapters.
- `infrastructure/market_data` contains input adapters, including the CSV adapter. Providers implement Application acquisition ports and map their source data into common DTOs without changing domain entities or use cases.
- `engines` and `presentation` are placeholders for later sprints.

Dependencies point inward: adapters depend on domain contracts, while domain types do not import database, UI, data-frame, or provider libraries. Session and engine factories are passed explicitly. Repository contracts use concrete domain entity types, and adapters explicitly map between SQLAlchemy rows and those entities. ORM models and persistence mappings stay inside Infrastructure.

Company industry revenue shares are individually constrained to `[0, 1]` in the database and domain. The application validates aggregate shares across all time-overlapping exposures for one company, requiring their total to be at most `1` on every date. This cross-row rule is not expressed as a database constraint because arbitrary time intervals cannot be safely enforced by a simple row check.

SQLite is the initial local store. SQLAlchemy types and Alembic migrations keep the schema portable to PostgreSQL, subject to normal migration review.

Market-data use cases receive provider and repository implementations through constructor injection. Providers receive `HistoricalPriceRequest` or `FxRateRequest` and return `RawDailyPriceRecord` or `RawFxRateRecord`; these DTOs contain typed dates, decimals, and integer volume, with row-level parsing errors where needed. Use cases own shared Domain validation, duplicate handling, provenance, and persistence. The CSV adapter alone accepts file paths and translates CSV cells into the common DTOs. A future IBKR adapter can translate its API response into the same DTOs and implement the same ports; no CSV behavior is part of that contract. Domain prices and rates retain source, observation date, publication date, availability time, collection time, and revision number. Stored observations are append-only: corrections are new revisions. Queries use an explicit point-in-time cutoff; source selection and UTC-date future filtering are specified in [MARKET_DATA_SPEC.md](MARKET_DATA_SPEC.md).
