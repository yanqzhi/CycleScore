# Development guide

1. Create and activate a Python 3.12+ virtual environment.
2. Install with `python -m pip install -e ".[dev]"` and copy `.env.example` to `.env`.
3. Run `cyclescope-init-db` to apply migrations and seed base industries.
4. Run `python -m pytest` for unit and temporary-SQLite integration checks.
5. Run `ruff check .`, `ruff format --check .`, and `mypy src` before submitting changes.

Add schema changes as Alembic revisions in `migrations/versions`. Do not edit a migration that has been applied to a shared database; add a new revision. Tests use isolated temporary databases. Master data should generally be deactivated or validity-dated rather than deleted; foreign-key restrictions guard referenced rows.
