# Architecture

CycleScope is a modular monolith packaged under `src/cyclescope`.

- `domain` contains framework-independent entities, validation exceptions, and persistence contracts.
- `application` reserves space for use cases and ports; Sprint 01 has no business workflows yet.
- `infrastructure/config` loads validated Pydantic Settings. `infrastructure/logging` configures standard-library console and rotating-file handlers.
- `infrastructure/database` contains SQLAlchemy mappings, engine/session setup, migration-backed initialization, and adapters.
- `engines` and `presentation` are placeholders for later sprints.

Dependencies point inward: adapters depend on domain contracts, while domain types do not import database, UI, data-frame, or provider libraries. Session and engine factories are passed explicitly. Repository contracts use concrete domain entity types, and adapters explicitly map between SQLAlchemy rows and those entities. ORM models and persistence mappings stay inside Infrastructure.

Company industry revenue shares are individually constrained to `[0, 1]` in the database and domain. The application validates aggregate shares across all time-overlapping exposures for one company, requiring their total to be at most `1` on every date. This cross-row rule is not expressed as a database constraint because arbitrary time intervals cannot be safely enforced by a simple row check.

SQLite is the initial local store. SQLAlchemy types and Alembic migrations keep the schema portable to PostgreSQL, subject to normal migration review.
