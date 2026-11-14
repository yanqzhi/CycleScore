"""Additive Alembic migration tests for the market-data schema."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cyclescope.infrastructure.database.models import (
    CompanyModel,
    DailyPriceModel,
    ExchangeModel,
    IndustryModel,
    LegacyListingReconciliationModel,
    ListingModel,
    ListingStatusEventModel,
    SecurityModel,
)
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
    command.upgrade(config, "0002_market_data")
    with Session(baseline_engine) as session:
        company = CompanyModel(name="Legacy issuer", country_code="JP")
        session.add(company)
        session.flush()
        legacy_rows = (
            ("1234", "XTKS", "JPY", "2010-01-04"),
            ("OTC1", "UNKNOWN-OTC", "ZZZ", "2012-01-01"),
            ("NODATE", "XNYS", "USD", None),
        )
        timestamp_text = datetime.now(UTC).isoformat(sep=" ")
        for ticker, exchange, currency, listing_date in legacy_rows:
            session.execute(
                text(
                    "INSERT INTO securities (company_id, ticker, exchange, currency, "
                    "security_type, listing_date, delisting_date, is_active, "
                    "created_at, updated_at) VALUES (:company_id, :ticker, "
                    ":exchange, :currency, "
                    ":security_type, :listing_date, NULL, 1, :now, :now)"
                ),
                {
                    "company_id": company.id,
                    "ticker": ticker,
                    "exchange": exchange,
                    "currency": currency,
                    "security_type": "common_stock",
                    "listing_date": listing_date,
                    "now": timestamp_text,
                },
            )
        legacy_security_id = session.execute(
            text("SELECT id FROM securities WHERE ticker = '1234'")
        ).scalar_one()
        session.commit()
    command.upgrade(config, "head")
    command.upgrade(config, "head")

    engine = create_database_engine(f"sqlite:///{database_path}")
    assert {
        "daily_prices",
        "fx_rates",
        "exchanges",
        "security_identifiers",
        "listings",
        "listing_status_events",
        "legacy_listing_reconciliation",
        "data_quality_reports",
        "data_anomalies",
    }.issubset(set(inspect(engine).get_table_names()))
    with Session(engine) as session:
        existing = session.query(IndustryModel).filter_by(code="KEEP").one()
        assert existing.name == "Existing record"
        legacy_security = session.get(SecurityModel, legacy_security_id)
        assert legacy_security is not None
        exchange = session.query(ExchangeModel).filter_by(exchange_code="XTKS").one()
        migrated_listing = session.query(ListingModel).filter_by(ticker="1234").one()
        assert migrated_listing.security_id == legacy_security.id
        assert migrated_listing.exchange_id == exchange.id
        assert migrated_listing.trading_currency == "JPY"
        assert migrated_listing.listing_date == date(2010, 1, 4)
        assert migrated_listing.security_id == legacy_security_id
        assert session.query(SecurityModel).count() == 3
        event = (
            session.query(ListingStatusEventModel)
            .filter_by(listing_id=migrated_listing.id)
            .one()
        )
        assert (event.status, event.effective_date) == ("active", date(2010, 1, 4))
        reconciled = session.query(LegacyListingReconciliationModel).all()
        assert {record.ticker for record in reconciled} == {"OTC1", "NODATE"}
        assert session.query(ListingModel).count() == 1
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
