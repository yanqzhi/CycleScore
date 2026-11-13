# CycleScope

CycleScope is an independent Python application for cyclical-stock intelligence. Sprint 01 provides the project foundation and master-data persistence only; analytical engines and market-data integrations are not implemented.

## Architecture

The package uses a modular monolith. Domain types and repository contracts stay independent of SQLAlchemy; Infrastructure contains SQLAlchemy mappings, SQLite setup, repositories, configuration, and logging. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Prerequisites and installation

Python 3.12 or newer is required.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Configuration uses Pydantic Settings. Environment variables use the `CYCLESCOPE_` prefix. See `.env.example` for available options. Defaults target a local SQLite database at `data/cyclescope.db`.

## Database

Initialize or upgrade schema and idempotently seed the seven initial industries:

```powershell
cyclescope-init-db
```

This runs Alembic `upgrade head`; it does not delete or recreate the database. See [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md).

## Development

```powershell
python -m pytest
ruff check .
ruff format --check .
mypy src
```

More workflow details are in [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md).
