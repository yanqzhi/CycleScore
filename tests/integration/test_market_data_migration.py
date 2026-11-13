"""Additive Alembic migration tests for the market-data schema."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cyclescope.infrastructure.database.models import DailyPriceModel, IndustryModel
from cyclescope.infrastructure.database.session import create_database_engine


def test_market_data_migration_preserves_master_data_and_enforces_foreign_keys(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "upgrade.db"
    config = Config(str(Path.cwd() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0001_master_data")

    baseline_engine = create_database_engine(f"sqlite:///{database_path}")
    with Session(baseline_engine) as session:
        session.add(IndustryModel(code="KEEP", name="Existing record"))
        session.commit()
    command.upgrade(config, "head")

    engine = create_database_engine(f"sqlite:///{database_path}")
    assert {"daily_prices", "fx_rates"}.issubset(set(inspect(engine).get_table_names()))
    with Session(engine) as session:
        existing = session.query(IndustryModel).filter_by(code="KEEP").one()
        assert existing.name == "Existing record"
        session.add(
            DailyPriceModel(
                security_id=999,
                observation_date=date(2024, 1, 2),
                open=1,
                high=1,
                low=1,
                close=1,
                volume=1,
                currency="USD",
                source_id=999,
                available_at=datetime.now(UTC),
                collected_at=datetime.now(UTC),
                revision_number=1,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()
    baseline_engine.dispose()
