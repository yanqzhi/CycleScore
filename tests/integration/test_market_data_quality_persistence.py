"""SQLite persistence, transaction, and point-in-time quality workflow tests."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from cyclescope.application.dto.data_quality import (
    FxQualityRequest,
    PriceQualityRequest,
)
from cyclescope.application.use_cases.quality_workflows import (
    AssessDailyPriceQuality,
    ManageMarketDataAnomaly,
)
from cyclescope.application.use_cases.revision_management import (
    MarketDataRevisionManagement,
)
from cyclescope.domain.entities import DailyPrice, FxRate
from cyclescope.domain.entities.data_quality import DataAnomaly
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.data_quality import (
    AnomalySeverity,
    AnomalyStatus,
    AnomalyType,
    DatasetType,
)
from cyclescope.domain.value_objects.market_data import CurrencyPair, MarketDataPeriod
from cyclescope.infrastructure.database.models import (
    CompanyModel,
    DailyPriceModel,
    DataSourceModel,
    FxRateModel,
    SecurityModel,
)
from cyclescope.infrastructure.database.models.data_quality import (
    DataAnomalyModel,
    DataQualityReportModel,
)
from cyclescope.infrastructure.database.repositories.data_quality import (
    SQLAlchemyDataQualityRepository,
)
from cyclescope.infrastructure.database.repositories.market_data import (
    SQLAlchemyDailyPriceRepository,
    SQLAlchemyFxRateRepository,
)
from cyclescope.infrastructure.market_data.quality.trading_calendar import (
    WeekdayTradingCalendar,
)

AS_OF = datetime(2026, 1, 12, 12, tzinfo=UTC)


def refs(session):
    company = CompanyModel(name="Quality issuer", country_code="US")
    source = DataSourceModel(code="QUALITY", name="Quality test", provider_type="test")
    session.add_all([company, source])
    session.flush()
    security = SecurityModel(company_id=company.id, security_type="common_stock")
    session.add(security)
    session.flush()
    return source.id, security.id


def price(
    security_id: int,
    source_id: int,
    day: date,
    close: str,
    revision: int,
    available: datetime,
) -> DailyPrice:
    value = Decimal(close)
    return DailyPrice(
        security_id=security_id,
        observation_date=day,
        open=value,
        high=value,
        low=value,
        close=value,
        adjusted_close=None,
        volume=100,
        currency="USD",
        source_id=source_id,
        publication_date=None,
        available_at=available,
        collected_at=available + timedelta(minutes=5),
        revision_number=revision,
        created_at=available,
        updated_at=available,
    )


def calendar():
    return WeekdayTradingCalendar({"EXCHANGE:1": (), "FX": ()})


def test_quality_report_and_missing_anomaly_persist_and_transition(session):
    source_id, security_id = refs(session)
    prices = SQLAlchemyDailyPriceRepository(session)
    prices.save(price(security_id, source_id, date(2026, 1, 5), "10", 1, AS_OF))
    quality = SQLAlchemyDataQualityRepository(session)
    use_case = AssessDailyPriceQuality(prices, quality, calendar())
    result = use_case.execute(
        PriceQualityRequest(
            security_id,
            date(2026, 1, 5),
            date(2026, 1, 6),
            source_id,
            AS_OF,
            1,
        )
    )
    assert result.report.id is not None
    assert result.report.expected_sessions == 2
    assert result.report.coverage_ratio == Decimal("50.0000")
    assert result.report.score is None
    assert result.report.status.value == "INSUFFICIENT_DATA"
    assert len(result.anomalies) == 1
    anomaly = result.anomalies[0]
    assert anomaly.id is not None and anomaly.quality_report_id == result.report.id
    assert anomaly.status == AnomalyStatus.OPEN
    assert quality.get_report(result.report.id) == result.report
    assert len(quality.list_anomalies(report_id=result.report.id)) == 1

    updated = ManageMarketDataAnomaly(quality).transition(
        anomaly.id, AnomalyStatus.ACKNOWLEDGED, AS_OF + timedelta(hours=1)
    )
    assert updated.status == AnomalyStatus.ACKNOWLEDGED
    resolved = ManageMarketDataAnomaly(quality).transition(
        anomaly.id, AnomalyStatus.RESOLVED, AS_OF + timedelta(hours=2)
    )
    assert resolved.resolved_at == AS_OF + timedelta(hours=2)
    session.commit()
    stored = session.get(DataAnomalyModel, anomaly.id)
    assert stored is not None and stored.status == "RESOLVED"


def test_price_quality_score_is_calculated_with_sufficient_history(session):
    source_id, security_id = refs(session)
    repository = SQLAlchemyDailyPriceRepository(session)
    days = (
        date(2026, 1, 5),
        date(2026, 1, 6),
        date(2026, 1, 7),
        date(2026, 1, 8),
        date(2026, 1, 9),
        date(2026, 1, 12),
    )
    for day in days:
        repository.save(price(security_id, source_id, day, "10", 1, AS_OF))
    result = AssessDailyPriceQuality(
        repository, SQLAlchemyDataQualityRepository(session), calendar()
    ).execute(PriceQualityRequest(security_id, days[0], days[-1], source_id, AS_OF, 1))
    assert result.report.status.value == "PASS"
    assert result.report.coverage_ratio == Decimal("100.0000")
    assert result.report.score == Decimal("100.0000")


def test_quality_persistence_respects_caller_rollback(session):
    source_id, security_id = refs(session)
    prices = SQLAlchemyDailyPriceRepository(session)
    prices.save(price(security_id, source_id, date(2026, 1, 5), "10", 1, AS_OF))
    result = AssessDailyPriceQuality(
        prices, SQLAlchemyDataQualityRepository(session), calendar()
    ).execute(
        PriceQualityRequest(
            security_id, date(2026, 1, 5), date(2026, 1, 6), source_id, AS_OF, 1
        )
    )
    report_id = result.report.id
    session.rollback()
    assert session.get(DataQualityReportModel, report_id) is None
    assert session.scalar(select(DataAnomalyModel.id)) is None


def test_fx_quality_assessment_persists_outlier_and_keeps_rates_unchanged(session):
    source_id, _ = refs(session)
    fx_repository = SQLAlchemyFxRateRepository(session)
    for day, value in ((date(2026, 1, 5), "150"), (date(2026, 1, 6), "165")):
        fx_repository.save(
            FxRate(
                base_currency="USD",
                quote_currency="JPY",
                observation_date=day,
                rate=Decimal(value),
                source_id=source_id,
                publication_date=None,
                available_at=AS_OF,
                collected_at=AS_OF,
                revision_number=1,
                created_at=AS_OF,
                updated_at=AS_OF,
            )
        )
    from cyclescope.application.use_cases.quality_workflows import AssessFxRateQuality

    use_case = AssessFxRateQuality(
        fx_repository, SQLAlchemyDataQualityRepository(session), calendar()
    )
    result = use_case.execute(
        FxQualityRequest(
            "USD", "JPY", date(2026, 1, 5), date(2026, 1, 6), source_id, AS_OF
        )
    )
    assert result.report.dataset_type == DatasetType.FX_RATE
    assert result.report.status.value == "FAIL"
    assert len(result.anomalies) == 1
    assert result.anomalies[0].severity == AnomalySeverity.ERROR
    assert session.query(FxRateModel).count() == 2
    assert session.query(DataAnomalyModel).count() == 1


def test_failed_anomaly_flush_rolls_back_report_and_anomalies(session):
    source_id, security_id = refs(session)
    prices = SQLAlchemyDailyPriceRepository(session)
    prices.save(price(security_id, source_id, date(2026, 1, 5), "10", 1, AS_OF))
    use_case = AssessDailyPriceQuality(
        prices, SQLAlchemyDataQualityRepository(session), calendar()
    )
    assessment = use_case._assessor.assess_prices(
        PriceQualityRequest(
            security_id, date(2026, 1, 5), date(2026, 1, 6), source_id, AS_OF, 1
        ),
        prices.get_by_security_and_period(
            security_id,
            MarketDataPeriod(date(2026, 1, 5), date(2026, 1, 6)),
            AS_OF,
            source_id,
        ),
        calendar(),
        detected_at=AS_OF,
    )
    report = assessment.report
    # An invalid FK fails after the report row has flushed, exercising the SAVEPOINT.
    detected = replace(
        DataAnomaly(
            dataset_type=DatasetType.DAILY_PRICE,
            observation_date=date(2026, 1, 5),
            source_id=source_id,
            revision_number=1,
            anomaly_type=AnomalyType.PRICE_MOVE,
            severity=AnomalySeverity.ERROR,
            detection_rule="test",
            detection_rule_version="1",
            detected_at=AS_OF,
            explanation="test FK failure",
            security_id=security_id,
        ),
        security_id=999999,
    )
    repo = SQLAlchemyDataQualityRepository(session)
    with pytest.raises(IntegrityError):
        repo.persist_assessment(report, (detected,))
    assert session.is_active
    assert session.scalar(select(DataQualityReportModel.id)) is None
    assert session.scalar(select(DataAnomalyModel.id)) is None


def test_revision_as_of_selection_and_comparison_preserve_history(session):
    source_id, security_id = refs(session)
    first_available = datetime(2026, 1, 6, 9, tzinfo=UTC)
    correction_available = datetime(2026, 1, 8, 9, tzinfo=UTC)
    repository = SQLAlchemyDailyPriceRepository(session)
    day = date(2026, 1, 5)
    repository.save(price(security_id, source_id, day, "10", 1, first_available))
    repository.save(price(security_id, source_id, day, "11", 2, correction_available))
    manager = MarketDataRevisionManagement(
        repository, SQLAlchemyFxRateRepository(session)
    )
    history = manager.price_revisions(security_id, day, source_id)
    assert [row.revision_number for row in history] == [1, 2]
    assert (
        manager.price_as_of(
            security_id, day, source_id, correction_available - timedelta(seconds=1)
        ).revision_number
        == 1
    )
    assert (
        manager.price_as_of(
            security_id, day, source_id, correction_available
        ).revision_number
        == 2
    )
    comparison = manager.compare_prices(history[0], history[1])
    assert any(change[0] == "close" for change in comparison.changes)
    assert comparison.earlier_available_at == first_available
    assert comparison.later_collected_at == correction_available + timedelta(minutes=5)
    assert (
        session.scalar(
            select(DailyPriceModel.id).where(DailyPriceModel.revision_number == 1)
        )
        is not None
    )


def test_revision_lookup_requires_explicit_source(session):
    manager = MarketDataRevisionManagement(
        SQLAlchemyDailyPriceRepository(session), SQLAlchemyFxRateRepository(session)
    )
    with pytest.raises(DomainValidationError, match="explicit source_id"):
        manager.price_revisions(1, date(2026, 1, 5), 0)


def test_fx_revision_as_of_and_comparison_are_source_scoped(session):
    source_id, _ = refs(session)
    repository = SQLAlchemyFxRateRepository(session)
    day = date(2026, 1, 5)
    first_time = datetime(2026, 1, 6, 9, tzinfo=UTC)
    second_time = datetime(2026, 1, 8, 9, tzinfo=UTC)
    for revision, rate, available in ((1, "150", first_time), (2, "151", second_time)):
        repository.save(
            FxRate(
                base_currency="USD",
                quote_currency="JPY",
                observation_date=day,
                rate=Decimal(rate),
                source_id=source_id,
                publication_date=None,
                available_at=available,
                collected_at=available,
                revision_number=revision,
                created_at=available,
                updated_at=available,
            )
        )
    manager = MarketDataRevisionManagement(
        SQLAlchemyDailyPriceRepository(session), repository
    )
    history = manager.fx_revisions(CurrencyPair("USD", "JPY"), day, source_id)
    assert (
        manager.fx_as_of(
            CurrencyPair("USD", "JPY"),
            day,
            source_id,
            second_time - timedelta(seconds=1),
        ).revision_number
        == 1
    )
    assert (
        manager.fx_as_of(
            CurrencyPair("USD", "JPY"), day, source_id, second_time
        ).revision_number
        == 2
    )
    assert manager.compare_fx(history[0], history[1]).changes[0][0] == "rate"
