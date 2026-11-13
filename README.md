# CycleScope

CycleScope is an independent Python application for cyclical-stock intelligence. It includes a multi-market issuer, security, exchange, identifier, and listing master, company industry exposures, and provider-independent infrastructure for importing and retrieving daily OHLCV prices and FX rates. Live provider integrations and analytical engines are not implemented.

## Architecture

The package uses a modular monolith. Domain types and repository contracts stay independent of SQLAlchemy; Application use cases depend on typed acquisition and repository ports; Infrastructure contains SQLAlchemy mappings, SQLite setup, repositories, configuration, logging, and input adapters. Security represents an instrument; Exchange-scoped Listing records hold tickers and trading lifecycle. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/MASTER_DATA_SPEC.md](docs/MASTER_DATA_SPEC.md), and [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md).

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

This runs Alembic `upgrade head`; it does not delete or recreate the database. Migrations preserve Security IDs, normalize recognized legacy listings, and retain unmappable rows for reconciliation. See [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md) and [docs/MASTER_DATA_SPEC.md](docs/MASTER_DATA_SPEC.md).

## CSV market-data import

CSV import is available through the CSV input adapter and injected application use cases. The CSV price columns are `date,open,high,low,close,volume`; `adjusted_close` and `publication_date` are optional. FX CSV columns are `base_currency,quote_currency,date,rate`; `publication_date` is optional. Prices and rates use decimal notation with a dot, and dates use `YYYY-MM-DD`. Application ports use `HistoricalPriceRequest` / `FxRateRequest` and common `RawDailyPriceRecord` / `RawFxRateRecord` DTOs; they have no CSV or file-path dependency. CSV paths are configured only on `CsvHistoricalMarketDataProvider`.

Example wiring (the security and data source must already exist):

```python
from datetime import UTC, datetime
from pathlib import Path

from cyclescope.application.dto.market_data import (
    HistoricalPriceRequest,
    ImportHistoricalPricesInput,
)
from cyclescope.application.use_cases.market_data import ImportHistoricalPrices
from cyclescope.infrastructure.database.repositories.market_data import (
    SQLAlchemyDailyPriceRepository,
)
from cyclescope.infrastructure.database.session import (
    create_database_engine,
    create_session_factory,
)
from cyclescope.infrastructure.config import get_settings
from cyclescope.infrastructure.market_data.csv_provider import (
    CsvHistoricalMarketDataProvider,
)

settings = get_settings()
engine = create_database_engine(settings.database_url)
session_factory = create_session_factory(engine)

with session_factory.begin() as session:
    summary = ImportHistoricalPrices(
        CsvHistoricalMarketDataProvider(price_file_path=Path("prices.csv")),
        SQLAlchemyDailyPriceRepository(session),
    ).execute(
        ImportHistoricalPricesInput(
            request=HistoricalPriceRequest(security_id=1, currency="USD"),
            source_id=1,
            available_at=datetime(2024, 1, 3, 8, tzinfo=UTC),
            collected_at=datetime(2024, 1, 3, 9, tzinfo=UTC),
            revision_number=1,
        )
    )
    print(
        summary.imported_records, summary.skipped_duplicates, summary.rejected_records
    )
```

The import summary lists row-level validation errors. Duplicate keys are skipped without overwriting stored data. Full format, provenance, revision, and availability rules are documented in [docs/MARKET_DATA_SPEC.md](docs/MARKET_DATA_SPEC.md).

## Development

```powershell
python -m pytest
ruff check .
ruff format --check .
mypy src
```

More workflow details are in [docs/DEVELOPMENT_GUIDE.md](docs/DEVELOPMENT_GUIDE.md).

CycleScore now includes a provider-neutral financial statement foundation for BS, PL, and CF data. It stores source-specific revisions with point-in-time availability, standardized item definitions, and source item mappings. See [Financial Data Specification](docs/FINANCIAL_DATA_SPEC.md). No live provider or analysis engine is included.
