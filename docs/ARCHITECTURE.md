# Architecture

CycleScope is a modular monolith packaged under `src/cyclescope`.

- `domain` contains framework-independent entities, validation exceptions, and persistence contracts.
- `application` reserves space for use cases and ports; Sprint 01 has no business workflows yet.
- `infrastructure/config` loads validated Pydantic Settings. `infrastructure/logging` configures standard-library console and rotating-file handlers.
- `infrastructure/database` contains SQLAlchemy mappings, engine/session setup, migration-backed initialization, and adapters.
- `engines` and `presentation` are placeholders for later sprints.

Dependencies point inward: adapters depend on domain contracts, while domain types do not import database, UI, data-frame, or provider libraries. Session and engine factories are passed explicitly. The database adapters return scalar dictionaries so ORM instances do not escape Infrastructure; application-specific domain records can replace these return values as use cases are introduced.

SQLite is the initial local store. SQLAlchemy types and Alembic migrations keep the schema portable to PostgreSQL, subject to normal migration review.
