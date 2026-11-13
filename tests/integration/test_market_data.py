"""Market-data import, repository, provenance, and retrieval tests."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cyclescope.application.dto.market_data import (
    GetHistoricalFxRatesInput,
    GetHistoricalPricesInput,
    ImportFxRatesInput,
    ImportHistoricalPricesInput,
)
from cyclescope.application.use_cases.market_data import (
    GetHistoricalFxRates,
    GetHistoricalPrices,
    ImportFxRates,
    ImportHistoricalPrices,
)
from cyclescope.domain.entities import DailyPrice, FxRate
from cyclescope.domain.value_objects.market_data import CurrencyPair, MarketDataPeriod
from cyclescope.infrastructure.database.models import (
    CompanyModel,
    DailyPriceModel,
    DataSourceModel,
    FxRateModel,
    SecurityModel,
)
from cyclescope.infrastructure.database.repositories.market_data import (
    SQLAlchemyDailyPriceRepository,
    SQLAlchemyFxRateRepository,
)
from cyclescope.infrastructure.market_data.csv_provider import (
    CsvHistoricalMarketDataProvider,
)

UTC_NOW = datetime(2024, 1, 5, 12, tzinfo=UTC)


def references(session: Session) -> tuple[int, int]:
    """Create an issuer, security, and source; return security/source IDs."""
    company = CompanyModel(name="Test Co", country_code="US")
    source = DataSourceModel(
        code="TEST_PROVIDER", name="Test provider", provider_type="csv"
    )
    session.add_all([company, source])
    session.flush()
    security = SecurityModel(
        company_id=company.id,
        ticker="TEST",
        exchange="NYSE",
        currency="USD",
        security_type="common_stock",
    )
    session.add(security)
    session.flush()
    return security.id, source.id


def test_csv_price_import_revisions_and_point_in_time_retrieval(
    session: Session, tmp_path: Path
) -> None:
    security_id, source_id = references(session)
    csv_path = tmp_path / "prices.csv"
    csv_path.write_text(
        "date,open,high,low,close,volume,adjusted_close,publication_date\n"
        "2024-01-02,10,12,9,11,100,10.5,2024-01-03\n"
        "2024-01-01,9,11,8,10,90,,\n"
        "2024-01-02,10,13,9,12,100,,\n"
        "2024-01-03,15,12,9,11,100,,\n",
        encoding="utf-8",
    )
    provider = CsvHistoricalMarketDataProvider()
    repository = SQLAlchemyDailyPriceRepository(session)
    importer = ImportHistoricalPrices(provider, repository)
    request = ImportHistoricalPricesInput(
        file_path=csv_path,
        security_id=security_id,
        currency="usd",
        source_id=source_id,
        available_at=datetime(2024, 1, 3, 8, tzinfo=UTC),
        collected_at=datetime(2024, 1, 3, 9, tzinfo=UTC),
    )
    first = importer.execute(request)
    assert (first.total_records, first.imported_records) == (4, 2)
    assert first.skipped_duplicates == 1
    assert first.rejected_records == 1
    assert "high" in first.validation_errors[0].message

    revised = importer.execute(
        ImportHistoricalPricesInput(
            file_path=csv_path,
            security_id=security_id,
            currency="USD",
            source_id=source_id,
            available_at=datetime(2024, 1, 5, 8, tzinfo=UTC),
            collected_at=datetime(2024, 1, 5, 9, tzinfo=UTC),
            revision_number=2,
        )
    )
    assert revised.imported_records == 2
    assert session.query(DailyPriceModel).count() == 4
    assert [
        record.revision_number
        for record in repository.get_revisions(security_id, date(2024, 1, 2), source_id)
    ] == [1, 2]

    getter = GetHistoricalPrices(repository)
    before_revision = getter.execute(
        GetHistoricalPricesInput(
            security_id,
            date(2024, 1, 1),
            date(2024, 1, 5),
            datetime(2024, 1, 4, 12, tzinfo=UTC),
        )
    )
    assert [item.observation_date for item in before_revision] == [
        date(2024, 1, 1),
        date(2024, 1, 2),
    ]
    assert all(item.revision_number == 1 for item in before_revision)
    latest = repository.get_latest_available(security_id, UTC_NOW)
    assert latest is not None and latest.revision_number == 2
    after_revision = getter.execute(
        GetHistoricalPricesInput(
            security_id,
            date(2024, 1, 1),
            date(2024, 1, 6),
            UTC_NOW,
        )
    )
    assert [item.revision_number for item in after_revision] == [2, 2]
    assert after_revision[1].publication_date == date(2024, 1, 3)
    assert after_revision[1].source_id == source_id


def test_price_repository_preserves_unique_revision_and_excludes_future_rows(
    session: Session,
) -> None:
    security_id, source_id = references(session)
    repository = SQLAlchemyDailyPriceRepository(session)
    entity = DailyPrice(
        security_id=security_id,
        observation_date=date(2024, 1, 6),
        open=Decimal("10"),
        high=Decimal("11"),
        low=Decimal("9"),
        close=Decimal("10"),
        adjusted_close=None,
        volume=10,
        currency="USD",
        source_id=source_id,
        publication_date=None,
        available_at=datetime(2024, 1, 5, tzinfo=UTC),
        collected_at=datetime(2024, 1, 5, tzinfo=UTC),
        revision_number=1,
        created_at=datetime(2024, 1, 5, tzinfo=UTC),
        updated_at=datetime(2024, 1, 5, tzinfo=UTC),
    )
    assert repository.save(entity)
    assert not repository.save(entity)
    assert repository.exists(security_id, entity.observation_date, source_id, 1)
    assert repository.get_latest_available(security_id, UTC_NOW) is None
    assert (
        repository.get_by_security_and_period(
            security_id,
            MarketDataPeriod(date(2024, 1, 1), date(2024, 1, 10)),
            UTC_NOW,
        )
        == []
    )


def test_fx_import_duplicate_revision_and_historical_retrieval(
    session: Session, tmp_path: Path
) -> None:
    _, source_id = references(session)
    csv_path = tmp_path / "rates.csv"
    csv_path.write_text(
        "base_currency,quote_currency,date,rate,publication_date\n"
        "usd,jpy,2024-01-02,145.25,2024-01-03\n"
        "USD,JPY,2024-01-02,146,,\n"
        "USD,USD,2024-01-03,1,,\n"
        "USD,JPY,2024-01-04,0,,\n",
        encoding="utf-8",
    )
    provider = CsvHistoricalMarketDataProvider()
    repository = SQLAlchemyFxRateRepository(session)
    importer = ImportFxRates(provider, repository)
    request = ImportFxRatesInput(
        csv_path,
        source_id,
        datetime(2024, 1, 3, 8, tzinfo=UTC),
        datetime(2024, 1, 3, 9, tzinfo=UTC),
    )
    summary = importer.execute(request)
    assert (summary.total_records, summary.imported_records) == (4, 1)
    assert summary.skipped_duplicates == 1
    assert summary.rejected_records == 2
    assert session.query(FxRateModel).count() == 1
    assert not repository.save(summary.imported_observations[0])

    updated = FxRate(
        base_currency="USD",
        quote_currency="JPY",
        observation_date=date(2024, 1, 2),
        rate=Decimal("146"),
        source_id=source_id,
        publication_date=date(2024, 1, 4),
        available_at=datetime(2024, 1, 5, 8, tzinfo=UTC),
        collected_at=datetime(2024, 1, 5, 9, tzinfo=UTC),
        revision_number=2,
    )
    assert repository.save(updated)
    assert session.query(FxRateModel).count() == 2
    assert [
        record.revision_number
        for record in repository.get_revisions(
            CurrencyPair("USD", "JPY"), date(2024, 1, 2), source_id
        )
    ] == [1, 2]
    getter = GetHistoricalFxRates(repository)
    before_update = getter.execute(
        GetHistoricalFxRatesInput(
            "USD",
            "JPY",
            date(2024, 1, 1),
            date(2024, 1, 4),
            datetime(2024, 1, 4, 12, tzinfo=UTC),
        )
    )
    assert before_update[0].rate == Decimal("145.250000000000")
    after_update = getter.execute(
        GetHistoricalFxRatesInput(
            "USD", "JPY", date(2024, 1, 1), date(2024, 1, 4), UTC_NOW
        )
    )
    assert after_update[0].revision_number == 2
    assert after_update[0].publication_date == date(2024, 1, 4)
    latest_rate = repository.get_latest_available(CurrencyPair("USD", "JPY"), UTC_NOW)
    assert latest_rate is not None and latest_rate.revision_number == 2


def test_market_data_foreign_keys_and_transaction_rollback(session: Session) -> None:
    repository = SQLAlchemyDailyPriceRepository(session)
    invalid = DailyPrice(
        security_id=999,
        observation_date=date(2024, 1, 2),
        open=Decimal("1"),
        high=Decimal("1"),
        low=Decimal("1"),
        close=Decimal("1"),
        adjusted_close=None,
        volume=1,
        currency="USD",
        source_id=999,
        publication_date=None,
        available_at=UTC_NOW,
        collected_at=UTC_NOW,
        revision_number=1,
        created_at=UTC_NOW,
        updated_at=UTC_NOW,
    )
    with pytest.raises(IntegrityError):
        repository.save(invalid)
    session.rollback()

    security_id, source_id = references(session)
    session.commit()
    with pytest.raises(RuntimeError):
        with session.begin():
            transactional_repository = SQLAlchemyDailyPriceRepository(session)
            assert transactional_repository.save(
                DailyPrice(
                    security_id=security_id,
                    observation_date=date(2024, 1, 2),
                    open=Decimal("1"),
                    high=Decimal("1"),
                    low=Decimal("1"),
                    close=Decimal("1"),
                    adjusted_close=None,
                    volume=1,
                    currency="USD",
                    source_id=source_id,
                    publication_date=None,
                    available_at=UTC_NOW,
                    collected_at=UTC_NOW,
                    revision_number=1,
                    created_at=UTC_NOW,
                    updated_at=UTC_NOW,
                )
            )
            raise RuntimeError("roll back market-data write")
    assert session.query(DailyPriceModel).count() == 0
