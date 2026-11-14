from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from cyclescope.application.dto.valuation_percentile import (
    HistoricalValuationPercentileRequest,
    lookback_start,
)
from cyclescope.application.use_cases.valuation_percentile import (
    CalculateHistoricalValuationPercentile,
)
from cyclescope.domain.entities.normalized_earnings import (
    DepreciationAmortizationSignConvention,
    EarningsMetric,
    NormalizationMethod,
)
from cyclescope.domain.entities.valuation import (
    ValuationInputReference,
    ValuationMetricCode,
    ValuationMetricValue,
    ValuationResultStatus,
    ValuationUnit,
)
from cyclescope.domain.entities.valuation_percentile import (
    HistoricalValuationObservation,
    PercentileConfidence,
    PercentileMetric,
    PercentilePolicy,
    ValuationLookbackPeriod,
    ValuationPercentileStatus,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.services.valuation_percentile import (
    calculate_valuation_percentile,
)

AS_OF = datetime(2026, 5, 15, 16, tzinfo=UTC)
POLICY = PercentilePolicy(
    minimum_observations=1,
    medium_observations=3,
    high_observations=4,
    confidence_coverage=Decimal("0.75"),
)


def observation(day: date, value: str, *, currency="USD", period="TTM", **kwargs):
    as_of = kwargs.pop("as_of", datetime.combine(day, datetime.min.time(), UTC))
    return HistoricalValuationObservation(
        observation_date=day,
        as_of=as_of,
        status=kwargs.pop("status", "AVAILABLE"),
        value=Decimal(value) if value is not None else None,
        currency=currency,
        unit=kwargs.pop("unit", "RATIO"),
        financial_period=period,
        calculation_version=kwargs.pop("calculation_version", 1),
        market_source_id=1,
        financial_source_ids=(1,),
        snapshot_id=kwargs.pop("snapshot_id", day.day),
        unavailable_reason=kwargs.pop("unavailable_reason", None),
        **kwargs,
    )


def calculate(current, history, expected, **kwargs):
    return calculate_valuation_percentile(
        security_id=1,
        company_id=2,
        metric=kwargs.get("metric", PercentileMetric.PER),
        lookback_period=ValuationLookbackPeriod.THREE_YEARS,
        as_of=AS_OF,
        current=current,
        observations=tuple(history),
        expected_sessions=tuple(expected) if expected is not None else None,
        currency=kwargs.get("currency", "USD"),
        unit=kwargs.get("unit", "RATIO"),
        financial_period=kwargs.get("period", "TTM"),
        calculation_version=kwargs.get("version", 1),
        policy=kwargs.get("policy", POLICY),
    )


def test_ecdf_ties_and_boundary_behavior_are_deterministic():
    days = tuple(date(2026, 5, n) for n in range(11, 15))
    values = tuple(
        observation(day, value)
        for day, value in zip(days, ("1", "2", "2", "4"), strict=True)
    )
    result = calculate(values[1], values, days)
    assert result.status == ValuationPercentileStatus.AVAILABLE
    assert result.percentile == Decimal("75.0000000")
    assert result.historical_minimum == Decimal("1")
    assert result.historical_maximum == Decimal("4")
    assert result.historical_median == Decimal("2.000000000000")
    assert result.coverage_ratio == Decimal("1.0000000")
    assert result.confidence == PercentileConfidence.HIGH
    assert result == calculate(values[1], values, days)
    assert calculate(values[0], values, days).percentile == Decimal("25.0000000")
    assert calculate(values[-1], values, days).percentile == Decimal("100.0000000")


def test_zero_negative_and_comparability_failures_are_excluded_with_reasons():
    days = tuple(date(2026, 5, n) for n in range(10, 17))
    history = (
        observation(days[0], "1"),
        observation(days[1], "0"),
        observation(days[2], "-2"),
        observation(days[3], "3", currency="EUR"),
        observation(days[4], "4", period="FY"),
        observation(days[5], "5", unit="PER_SHARE"),
        observation(days[6], "6", calculation_version=2),
    )
    result = calculate(history[0], history, days)
    assert result.valid_observations == 1
    assert result.excluded_observations == 6
    assert {row.reason for row in result.observations if not row.included} == {
        "Valuation multiple must be positive.",
        "Currency differs from the current valuation.",
        "Financial period basis differs from the current valuation.",
        "Unit differs from the current valuation.",
        "Calculation version differs from the current valuation.",
    }


@pytest.mark.parametrize(
    ("metric", "status", "reason"),
    [
        (PercentileMetric.PER, "NOT_APPLICABLE", "EPS must be positive."),
        (PercentileMetric.EV_EBITDA, "NOT_APPLICABLE", "EBITDA must be positive."),
        (PercentileMetric.PBR, "INVALID_INPUT", "Book value per share is invalid."),
        (PercentileMetric.NORMALIZED_PER, "UNAVAILABLE", "Normalized EPS is missing."),
        (
            PercentileMetric.NORMALIZED_EV_EBITDA,
            "INVALID_INPUT",
            "Normalized EBITDA is invalid.",
        ),
    ],
)
def test_invalid_metric_observations_are_excluded_without_zero_substitution(
    metric, status, reason
):
    bad_day = date(2026, 5, 13)
    current_day = date(2026, 5, 14)
    bad = observation(
        bad_day,
        None,
        status=status,
        unavailable_reason=reason,
        snapshot_id=13,
    )
    current = observation(current_day, "8", snapshot_id=14)
    result = calculate(
        current,
        (bad, current),
        (bad_day, current_day),
        metric=metric,
        policy=PercentilePolicy(1, 2, 3, Decimal("0.5")),
    )
    assert result.valid_observations == 1
    assert result.excluded_observations == 1
    assert result.historical_minimum == Decimal("8")
    assert next(row for row in result.observations if not row.included).reason == reason


def test_empty_history_and_missing_current_are_insufficient_data():
    result = calculate(None, (), (date(2026, 5, 14),))
    assert result.status == ValuationPercentileStatus.INSUFFICIENT_DATA
    assert result.valid_observations == 0
    assert result.percentile is None
    assert result.current_value is None


def test_duplicate_dates_keep_latest_snapshot_and_explain_superseded_row():
    day = date(2026, 5, 14)
    first = observation(day, "2", snapshot_id=1)
    later = observation(day, "3", snapshot_id=2)
    result = calculate(later, (first, later), (day,))
    assert result.valid_observations == 1
    assert result.excluded_observations == 1
    assert result.percentile == Decimal("100.0000000")
    assert any("Superseded" in (row.reason or "") for row in result.observations)


def test_insufficient_samples_missing_calendar_and_invalid_current_are_explicit():
    day = date(2026, 5, 14)
    valid = observation(day, "2")
    insufficient = calculate(valid, (valid,), (day,), policy=PercentilePolicy())
    assert insufficient.status == ValuationPercentileStatus.INSUFFICIENT_DATA
    assert insufficient.percentile is None
    unknown_calendar = calculate(valid, (valid,), None)
    assert unknown_calendar.status == ValuationPercentileStatus.UNAVAILABLE
    invalid_current = observation(day, "0")
    invalid = calculate(invalid_current, (valid,), (day,))
    assert invalid.status == ValuationPercentileStatus.INVALID_INPUT
    assert "positive" in invalid.status_reason


def test_future_cutoff_and_non_session_observations_are_excluded():
    day = date(2026, 5, 14)
    future_cutoff = observation(day, "3", as_of=datetime(2026, 5, 15, tzinfo=UTC))
    non_session = observation(day + timedelta(days=1), "4")
    late_revision = observation(
        day,
        "99",
        references=(
            ValuationInputReference(
                "FINANCIAL_LINE",
                9,
                1,
                2,
                datetime(2026, 5, 15, tzinfo=UTC),
                parent_record_id=10,
                financial_item_code="EPS",
                financial_period="FY",
                period_end=day,
            ),
        ),
    )
    valid = observation(day, "2", snapshot_id=3)
    result = calculate(
        valid, (future_cutoff, non_session, late_revision, valid), (day,)
    )
    assert result.valid_observations == 1
    assert result.excluded_observations == 3
    assert any("cutoff" in (row.reason or "") for row in result.observations)
    assert any("trading session" in (row.reason or "") for row in result.observations)
    assert any("not available" in (row.reason or "") for row in result.observations)


def test_lookback_periods_use_calendar_years_and_listing_boundary():
    as_of = datetime(2024, 2, 29, 10, tzinfo=UTC)
    assert lookback_start(ValuationLookbackPeriod.THREE_YEARS, as_of, None) == date(
        2021, 2, 28
    )
    assert lookback_start(
        ValuationLookbackPeriod.FIVE_YEARS, AS_OF, date(2024, 1, 1)
    ) == date(2024, 1, 1)
    assert lookback_start(
        ValuationLookbackPeriod.AVAILABLE_HISTORY, AS_OF, date(2012, 1, 1)
    ) == date(2012, 1, 1)


class _SecurityRepository:
    def get_by_id(self, security_id):
        return SimpleNamespace(id=security_id, company_id=2)


class _ListingRepository:
    def list_by_security(self, security_id):
        return []


class _ValuationRepository:
    def __init__(self, rows):
        self.rows = rows

    def list_by_security(self, security_id, metric_code=None, **kwargs):
        return [
            row
            for row in self.rows
            if metric_code is None or row.metric_code == metric_code
        ]


class _NormalizedRepository:
    def __init__(self, rows):
        self.rows = rows

    def list_by_company(self, company_id, *, metric=None, as_of=None, start_date=None):
        return [row for row in self.rows if row.metric == metric]


class _ResultRepository:
    def create(self, result):
        return result


class _Calendar:
    def __init__(self, sessions):
        self.sessions = sessions

    def expected_sessions(self, calendar_id, start_date, end_date):
        return tuple(day for day in self.sessions if start_date <= day <= end_date)


class _Unused:
    def execute(self, request):
        raise AssertionError("Cached normalized history should not be reconstructed.")


class _MissingNormalizedRepository:
    def list_by_company(self, company_id, *, metric=None, as_of=None, start_date=None):
        return []


class _InputBuilder:
    def execute(self, request):
        self.request = request
        return SimpleNamespace(security_id=request.security_id)


class _HistoricalSprintTen:
    def __init__(self):
        self.request = None

    def execute(self, request):
        self.request = request
        price_reference = ValuationInputReference(
            "DAILY_PRICE",
            21,
            1,
            1,
            request.as_of,
            observation_date=request.as_of.date(),
        )
        return tuple(
            SimpleNamespace(
                id=metric_index,
                metric=metric,
                as_of=request.as_of,
                method=request.method,
                requested_window_years=request.window_years,
                effective_window_years=request.window_years,
                da_sign_convention=request.da_sign_convention,
                valuation_input_references=(price_reference,),
                normalized_valuation_status=ValuationResultStatus.AVAILABLE,
                normalized_valuation_value=Decimal("10"),
                currency="USD",
                status_reason=None,
                normalized_valuation_reason=None,
                calculation_version=1,
            )
            for metric_index, metric in enumerate(EarningsMetric, start=1)
        )


def test_application_supports_all_five_metrics_and_cached_pit_normalized_history():
    days = tuple(date(2026, 4, n) for n in range(1, 21))
    valuation_rows = []
    for metric in (
        ValuationMetricCode.PER,
        ValuationMetricCode.PBR,
        ValuationMetricCode.EV_EBITDA,
    ):
        for index, day in enumerate(days, start=1):
            valuation_rows.append(
                ValuationMetricValue(
                    security_id=1,
                    metric_code=metric,
                    observation_date=day,
                    as_of=datetime.combine(day, datetime.min.time(), UTC),
                    status=ValuationResultStatus.AVAILABLE,
                    value=Decimal(index),
                    currency="USD",
                    unit=ValuationUnit.RATIO,
                    financial_period="TTM",
                    eps_calculation_method=None,
                    calculation_version=1,
                    price_observation_id=index,
                    price_source_id=1,
                    price_revision_number=1,
                    price_available_at=datetime.combine(day, datetime.min.time(), UTC),
                    financial_statement_ids=(),
                    financial_source_ids=(1,),
                    financial_statement_available_ats=(),
                    id=index + list(ValuationMetricCode).index(metric) * 100,
                )
            )
    normalized_rows = []
    for metric in (EarningsMetric.EPS, EarningsMetric.EBITDA):
        for index, day in enumerate(days, start=1):
            as_of = datetime.combine(day, datetime.min.time(), UTC)
            normalized_rows.append(
                SimpleNamespace(
                    id=index + list(EarningsMetric).index(metric) * 100,
                    metric=metric,
                    as_of=as_of,
                    method=NormalizationMethod.ARITHMETIC_MEAN,
                    requested_window_years=5,
                    effective_window_years=5,
                    da_sign_convention=DepreciationAmortizationSignConvention.POSITIVE_EXPENSE,
                    valuation_input_references=(
                        ValuationInputReference(
                            "DAILY_PRICE",
                            index,
                            1,
                            1,
                            as_of,
                            observation_date=day,
                        ),
                        ValuationInputReference(
                            "FINANCIAL_LINE",
                            index + 100,
                            1,
                            1,
                            as_of,
                            parent_record_id=1,
                            financial_item_code="EPS",
                            financial_period="FY",
                            period_end=day,
                        ),
                    ),
                    normalized_valuation_status=ValuationResultStatus.AVAILABLE,
                    normalized_valuation_value=Decimal(index),
                    currency="USD",
                    status_reason=None,
                    normalized_valuation_reason=None,
                    calculation_version=1,
                )
            )
    calculator = CalculateHistoricalValuationPercentile(
        _SecurityRepository(),
        _ListingRepository(),
        _ValuationRepository(valuation_rows),
        _NormalizedRepository(normalized_rows),
        _ResultRepository(),
        _Calendar(days),
        _Unused(),
        _Unused(),
    )
    for metric in PercentileMetric:
        result = calculator.execute(
            HistoricalValuationPercentileRequest(
                security_id=1,
                metric=metric,
                lookback_period=ValuationLookbackPeriod.THREE_YEARS,
                as_of=AS_OF,
                calendar_id="TEST",
                da_sign_convention=DepreciationAmortizationSignConvention.POSITIVE_EXPENSE,
                policy=PercentilePolicy(1, 10, 20, Decimal("0.8")),
            )
        ).result
        assert result.status == ValuationPercentileStatus.AVAILABLE
        assert result.valid_observations == 20
        assert result.percentile == Decimal("100.0000000")


def test_missing_historical_normalized_result_reuses_sprint10_at_historical_cutoff():
    day = date(2026, 4, 17)
    historical_as_of = datetime(2026, 4, 17, 16, tzinfo=UTC)
    base = ValuationMetricValue(
        security_id=1,
        metric_code=ValuationMetricCode.PER,
        observation_date=day,
        as_of=historical_as_of,
        status=ValuationResultStatus.AVAILABLE,
        value=Decimal("12"),
        currency="USD",
        unit=ValuationUnit.RATIO,
        financial_period="TTM",
        eps_calculation_method=None,
        calculation_version=1,
        price_observation_id=21,
        price_source_id=1,
        price_revision_number=1,
        price_available_at=historical_as_of,
        financial_statement_ids=(),
        financial_source_ids=(1,),
        financial_statement_available_ats=(),
        id=21,
    )
    builder = _InputBuilder()
    sprint10 = _HistoricalSprintTen()
    calculator = CalculateHistoricalValuationPercentile(
        _SecurityRepository(),
        _ListingRepository(),
        _ValuationRepository([base]),
        _MissingNormalizedRepository(),
        _ResultRepository(),
        _Calendar((day,)),
        builder,
        sprint10,
    )
    result = calculator.execute(
        HistoricalValuationPercentileRequest(
            security_id=1,
            metric=PercentileMetric.NORMALIZED_PER,
            lookback_period=ValuationLookbackPeriod.THREE_YEARS,
            as_of=AS_OF,
            calendar_id="TEST",
            da_sign_convention=DepreciationAmortizationSignConvention.POSITIVE_EXPENSE,
            policy=PercentilePolicy(1, 2, 3, Decimal("0.8")),
        )
    ).result
    assert builder.request.as_of == historical_as_of
    assert sprint10.request.as_of == historical_as_of
    assert sprint10.request.valuation_inputs is not None
    assert sprint10.request.valuation_inputs.security_id == 1
    assert result.current_value == Decimal("10")
    assert result.status == ValuationPercentileStatus.AVAILABLE


def test_multiple_source_series_require_and_obey_explicit_source_selection():
    days = tuple(date(2026, 4, n) for n in range(1, 21))
    snapshots = []
    for source_id in (1, 2):
        for index, day in enumerate(days, start=1):
            as_of = datetime.combine(day, datetime.min.time(), UTC)
            snapshots.append(
                ValuationMetricValue(
                    security_id=1,
                    metric_code=ValuationMetricCode.PER,
                    observation_date=day,
                    as_of=as_of,
                    status=ValuationResultStatus.AVAILABLE,
                    value=Decimal(index + (source_id - 1) * 100),
                    currency="USD",
                    unit=ValuationUnit.RATIO,
                    financial_period="TTM",
                    eps_calculation_method=None,
                    calculation_version=1,
                    price_observation_id=index,
                    price_source_id=source_id,
                    price_revision_number=1,
                    price_available_at=as_of,
                    financial_statement_ids=(),
                    financial_source_ids=(1,),
                    financial_statement_available_ats=(),
                    id=index + source_id * 100,
                )
            )
        future_day = date(2026, 5, 16)
        future_as_of = datetime.combine(future_day, datetime.min.time(), UTC)
        snapshots.append(
            ValuationMetricValue(
                security_id=1,
                metric_code=ValuationMetricCode.PER,
                observation_date=future_day,
                as_of=future_as_of,
                status=ValuationResultStatus.AVAILABLE,
                value=Decimal("999"),
                currency="USD",
                unit=ValuationUnit.RATIO,
                financial_period="TTM",
                eps_calculation_method=None,
                calculation_version=1,
                price_observation_id=999,
                price_source_id=source_id,
                price_revision_number=1,
                price_available_at=future_as_of,
                financial_statement_ids=(),
                financial_source_ids=(1,),
                financial_statement_available_ats=(),
                id=999 + source_id * 100,
            )
        )
    calculator = CalculateHistoricalValuationPercentile(
        _SecurityRepository(),
        _ListingRepository(),
        _ValuationRepository(snapshots),
        _MissingNormalizedRepository(),
        _ResultRepository(),
        _Calendar(days),
        _Unused(),
        _Unused(),
    )
    request = HistoricalValuationPercentileRequest(
        security_id=1,
        metric=PercentileMetric.PER,
        lookback_period=ValuationLookbackPeriod.THREE_YEARS,
        as_of=AS_OF,
        calendar_id="TEST",
        policy=PercentilePolicy(1, 10, 20, Decimal("0.8")),
    )
    with pytest.raises(DomainValidationError, match="market_source_id is required"):
        calculator.execute(request)
    selected = calculator.execute(
        HistoricalValuationPercentileRequest(
            security_id=request.security_id,
            metric=request.metric,
            lookback_period=request.lookback_period,
            as_of=request.as_of,
            calendar_id=request.calendar_id,
            market_source_id=1,
            policy=request.policy,
        )
    ).result
    assert selected.valid_observations == 20
    assert {row.market_source_id for row in selected.observations} == {1}
    assert selected.observation_end == days[-1]
