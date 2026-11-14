"""Tests for coverage, quality scoring, outliers, and anomaly lifecycle."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from cyclescope.application.dto.data_quality import (
    FxQualityRequest,
    PriceQualityRequest,
)
from cyclescope.application.use_cases.market_data_quality import (
    MarketDataQualityAssessor,
)
from cyclescope.domain.entities import DailyPrice, FxRate
from cyclescope.domain.entities.data_quality import DataAnomaly
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.data_quality import (
    AnomalySeverity,
    AnomalyStatus,
    AnomalyType,
    CalendarStatus,
    DataQualityConfig,
    DatasetType,
    QualityStatus,
)
from cyclescope.infrastructure.market_data.quality.trading_calendar import (
    WeekdayTradingCalendar,
)

AS_OF = datetime(2026, 2, 1, tzinfo=UTC)
NOW = datetime(2026, 2, 1, tzinfo=UTC)


def price(
    day: date, close: str, *, volume: int = 100, source: int = 1, rev: int = 1
) -> DailyPrice:
    close_d = Decimal(close)
    return DailyPrice(
        security_id=10,
        observation_date=day,
        open=close_d,
        high=close_d,
        low=close_d,
        close=close_d,
        adjusted_close=None,
        volume=volume,
        currency="USD",
        source_id=source,
        publication_date=None,
        available_at=NOW,
        collected_at=NOW,
        revision_number=rev,
        created_at=NOW,
        updated_at=NOW,
    )


def fx(day: date, rate: str) -> FxRate:
    return FxRate(
        base_currency="USD",
        quote_currency="JPY",
        observation_date=day,
        rate=Decimal(rate),
        source_id=1,
        publication_date=None,
        available_at=NOW,
        collected_at=NOW,
        revision_number=1,
        created_at=NOW,
        updated_at=NOW,
    )


class Calendar:
    def expected_sessions(self, calendar_id, start_date, end_date):
        return WeekdayTradingCalendar(
            {calendar_id: (date(2026, 1, 6),)}
        ).expected_sessions(calendar_id, start_date, end_date)


def test_missing_sessions_exclude_weekends_and_exchange_holidays():
    assessor = MarketDataQualityAssessor()
    request = PriceQualityRequest(
        10,
        date(2026, 1, 5),
        date(2026, 1, 11),
        1,
        AS_OF,
        7,
    )
    result = assessor.assess_prices(
        request,
        (price(date(2026, 1, 5), "10"), price(date(2026, 1, 7), "10")),
        Calendar(),
        detected_at=NOW,
    )
    assert result.report.expected_sessions == 4
    assert result.report.available_records == 2
    assert result.report.missing_sessions == 2
    assert result.report.coverage_ratio == Decimal("50")
    assert result.report.first_available_date == date(2026, 1, 5)
    assert result.report.last_available_date == date(2026, 1, 7)
    assert result.report.status == QualityStatus.INSUFFICIENT_DATA
    assert sum(count for _, count in result.report.anomaly_counts) == 2


def test_unknown_calendar_and_zero_expected_sessions_are_explicit():
    assessor = MarketDataQualityAssessor()
    request = PriceQualityRequest(
        10, date(2026, 1, 5), date(2026, 1, 5), 1, AS_OF, None
    )
    unknown = assessor.assess_prices(
        request, (price(date(2026, 1, 5), "10"),), Calendar()
    )
    assert unknown.report.status == QualityStatus.INSUFFICIENT_DATA
    assert unknown.report.calendar_status == CalendarStatus.UNKNOWN_CALENDAR
    assert unknown.report.score is None
    assert "UNKNOWN_CALENDAR" in unknown.report.explanation

    no_sessions_request = PriceQualityRequest(
        10, date(2026, 1, 10), date(2026, 1, 11), 1, AS_OF, 7
    )
    not_applicable = assessor.assess_prices(
        no_sessions_request, (), Calendar(), detected_at=NOW
    )
    assert not_applicable.report.status == QualityStatus.NOT_APPLICABLE
    assert not_applicable.report.calendar_status == CalendarStatus.NOT_APPLICABLE
    assert not_applicable.report.expected_sessions == 0
    assert not_applicable.report.coverage_ratio is None
    assert not_applicable.report.score is None


def test_price_move_and_volume_outlier_are_candidates_not_corrections():
    sessions = tuple(
        date(2026, 1, 5) + timedelta(days=offset) for offset in (0, 1, 2, 3, 4, 5)
    )
    rows = tuple(
        price(day, "10" if index < 5 else "16", volume=100 if index < 5 else 1000)
        for index, day in enumerate(sessions)
    )
    assessor = MarketDataQualityAssessor(
        DataQualityConfig(
            version="thresholds-test-v2", price_move_threshold=Decimal("0.20")
        )
    )
    request = PriceQualityRequest(10, sessions[0], sessions[-1], 1, AS_OF, 7)
    result = assessor.assess_prices(request, rows, Calendar(), detected_at=NOW)
    kinds = {anomaly.anomaly_type for anomaly in result.anomalies}
    assert AnomalyType.PRICE_MOVE in kinds
    assert AnomalyType.ABNORMAL_VOLUME in kinds
    assert all(
        anomaly.severity
        in (AnomalySeverity.ERROR, AnomalySeverity.CRITICAL, AnomalySeverity.WARNING)
        for anomaly in result.anomalies
    )
    assert result.report.config_version == "thresholds-test-v2"
    assert dict(result.report.config_snapshot)["price_move_threshold"] == "0.20"
    assert tuple(item.close for item in rows) == tuple(
        Decimal("10") for _ in range(5)
    ) + (Decimal("16"),)


def test_configured_weights_are_used_and_snapshotted_exactly():
    sessions = tuple(date(2025, 12, 31) + timedelta(days=i) for i in range(6))
    rows = (
        *(price(day, "10") for day in sessions[:-1]),
        price(sessions[-1], "10"),
        price(sessions[-1], "11"),
    )
    weights = (
        ("completeness", Decimal("0.60")),
        ("structural_validity", Decimal("0.10")),
        ("consistency", Decimal("0.10")),
        ("outlier_assessment", Decimal("0.10")),
        ("provenance", Decimal("0.10")),
    )
    config = DataQualityConfig(weights=weights)
    request = PriceQualityRequest(10, sessions[-1], sessions[-1], 1, AS_OF, 7)
    result = MarketDataQualityAssessor(config).assess_prices(
        request, rows, Calendar(), detected_at=NOW
    )
    component_scores = {item.name: item.score for item in result.report.components}
    expected = sum(
        (component_scores[name] * weight for name, weight in weights), Decimal(0)
    )
    assert result.report.score == expected
    assert result.report.score != Decimal("100")
    snapshot = dict(result.report.config_snapshot)
    assert {name: Decimal(snapshot[f"weight.{name}"]) for name, _ in weights} == dict(
        weights
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ("duplicate", "unique"),
        ("missing", "Missing"),
        ("unknown", "Unknown"),
        ("negative", "non-negative"),
        ("nan", "finite"),
        ("infinity", "finite"),
        ("sum", "sum exactly"),
    ],
)
def test_invalid_quality_weights_are_rejected(change, message):
    weights = list(DataQualityConfig().weights)
    if change == "duplicate":
        weights[-1] = weights[0]
    elif change == "missing":
        weights.pop()
    elif change == "unknown":
        weights[-1] = ("unknown", weights[-1][1])
    elif change == "negative":
        weights[0] = (weights[0][0], Decimal("-0.1"))
        weights[-1] = (weights[-1][0], Decimal("0.5"))
    elif change == "nan":
        weights[0] = (weights[0][0], Decimal("NaN"))
    elif change == "infinity":
        weights[0] = (weights[0][0], Decimal("Infinity"))
    elif change == "sum":
        weights[0] = (weights[0][0], Decimal("0.2"))
    with pytest.raises(DomainValidationError, match=message):
        DataQualityConfig(weights=tuple(weights))


def test_unavailable_component_remains_unscored_and_no_weight_is_redistributed():
    request = PriceQualityRequest(
        10, date(2026, 1, 5), date(2026, 1, 5), 1, AS_OF, None
    )
    result = MarketDataQualityAssessor().assess_prices(
        request, (price(date(2026, 1, 5), "10"),), Calendar(), detected_at=NOW
    )
    component = next(
        item for item in result.report.components if item.name == "completeness"
    )
    assert component.score is None and component.weight == Decimal("0.30")
    assert result.report.score is None
    assert result.report.status == QualityStatus.INSUFFICIENT_DATA


def test_price_outlier_uses_pre_report_history_without_reporting_it():
    report_start = date(2026, 1, 30)
    history = [
        price(report_start - timedelta(days=offset), "10", volume=100)
        for offset in range(20, 0, -1)
    ]
    first_report_day = price(report_start, "20", volume=1000)
    later_future = price(report_start + timedelta(days=1), "1000", volume=100000)
    request = PriceQualityRequest(10, report_start, report_start, 1, AS_OF, 7)
    result = MarketDataQualityAssessor().assess_prices(
        request, (*history, first_report_day, later_future), Calendar(), detected_at=NOW
    )
    kinds = [item.anomaly_type for item in result.anomalies]
    assert kinds.count(AnomalyType.PRICE_MOVE) == 1
    assert kinds.count(AnomalyType.ABNORMAL_VOLUME) == 1
    assert result.report.available_records == 1
    assert result.report.first_available_date == report_start
    assert result.report.last_available_date == report_start
    assert all(item.observation_date == report_start for item in result.anomalies)


def test_volume_baseline_uses_the_twenty_preceding_observations():
    report_start = date(2026, 1, 30)
    history = [
        price(
            report_start - timedelta(days=offset),
            "10",
            volume=1000 if offset > 5 else 100,
        )
        for offset in range(20, 0, -1)
    ]
    report_row = price(report_start, "10", volume=600)
    request = PriceQualityRequest(10, report_start, report_start, 1, AS_OF, 7)
    result = MarketDataQualityAssessor().assess_prices(
        request, (*history, report_row), Calendar(), detected_at=NOW
    )
    assert not any(
        item.anomaly_type == AnomalyType.ABNORMAL_VOLUME for item in result.anomalies
    )


def test_price_outlier_excludes_history_unavailable_at_as_of_and_future_rows():
    report_start = date(2026, 1, 30)
    prior = price(report_start - timedelta(days=1), "10", volume=100)
    prior = __import__("dataclasses").replace(
        prior, available_at=AS_OF + timedelta(seconds=1)
    )
    rows = [
        price(report_start + timedelta(days=offset), "10", volume=100)
        for offset in range(6)
    ]
    future = price(report_start + timedelta(days=6), "100", volume=100000)
    request = PriceQualityRequest(
        10, report_start, report_start + timedelta(days=5), 1, AS_OF, 7
    )
    result = MarketDataQualityAssessor().assess_prices(
        request, (prior, *rows, future), Calendar(), detected_at=NOW
    )
    assert not any(
        item.anomaly_type in (AnomalyType.PRICE_MOVE, AnomalyType.ABNORMAL_VOLUME)
        and item.observation_date == report_start
        for item in result.anomalies
    )


def test_fx_move_and_duplicate_detection_keep_sources_separate():
    assessor = MarketDataQualityAssessor()
    first = fx(date(2026, 1, 5), "150")
    second_source = fx(date(2026, 1, 5), "151")
    second_source = __import__("dataclasses").replace(second_source, source_id=2)
    moved = fx(date(2026, 1, 6), "165")
    request = FxQualityRequest(
        "usd", "jpy", date(2026, 1, 5), date(2026, 1, 6), None, AS_OF
    )
    result = assessor.assess_fx(
        request, (first, first, second_source, moved), Calendar(), detected_at=NOW
    )
    kinds = [anomaly.anomaly_type for anomaly in result.anomalies]
    assert AnomalyType.DUPLICATE_EXACT in kinds
    assert AnomalyType.DUPLICATE_CONFLICT in kinds
    assert AnomalyType.FX_MOVE in kinds


def test_anomaly_lifecycle_is_explicit_and_terminal():
    anomaly = DataAnomaly(
        DatasetType.DAILY_PRICE,
        date(2026, 1, 5),
        1,
        1,
        AnomalyType.PRICE_MOVE,
        AnomalySeverity.WARNING,
        "price_move",
        "v1",
        NOW,
        "Review sudden price move.",
        security_id=10,
    )
    acknowledged = anomaly.transition(AnomalyStatus.ACKNOWLEDGED, NOW)
    resolved = acknowledged.transition(AnomalyStatus.RESOLVED, NOW + timedelta(hours=1))
    assert resolved.resolved_at == NOW + timedelta(hours=1)
    with pytest.raises(DomainValidationError, match="Terminal"):
        resolved.transition(AnomalyStatus.FALSE_POSITIVE, NOW + timedelta(hours=2))
    with pytest.raises(DomainValidationError, match="back to OPEN"):
        acknowledged.transition(AnomalyStatus.OPEN, NOW)


def test_unknown_calendar_type_is_rejected_by_concrete_calendar():
    with pytest.raises(DomainValidationError, match="Unknown trading calendar"):
        WeekdayTradingCalendar({}).expected_sessions(
            "EXCHANGE:404", date(2026, 1, 1), date(2026, 1, 2)
        )
