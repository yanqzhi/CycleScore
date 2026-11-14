from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from cyclescope.application.dto.normalized_earnings import NormalizedEarningsRequest
from cyclescope.application.use_cases.normalized_earnings import (
    CalculateNormalizedEarnings,
)
from cyclescope.domain.entities.normalized_earnings import (
    EarningsConfidence,
    EarningsInputReference,
    EarningsMetric,
    EarningsResultStatus,
    FiscalEarningsObservation,
    NormalizationMethod,
    analyze_historical_earnings,
)
from cyclescope.domain.entities.valuation import (
    ValuationInputs,
    ValuationMetricCode,
    ValuationResultStatus,
)
from cyclescope.domain.services.valuation import (
    calculate_metric,
    default_metric_definitions,
)

AS_OF = datetime(2026, 6, 1, 12, tzinfo=UTC)


def _observation(year: int, value: str, *, available_at=AS_OF - timedelta(days=1)):
    reference = EarningsInputReference(
        statement_id=year,
        statement_item_id=year,
        source_id=1,
        revision_number=1,
        fiscal_year=year,
        fiscal_period="FY",
        item_code="NET_INCOME",
        period_start=date(year, 1, 1),
        period_end=date(year, 12, 31),
        available_at=available_at,
    )
    return FiscalEarningsObservation(
        fiscal_year=year,
        value=Decimal(value),
        references=(reference,),
        period_start=date(year, 1, 1),
        period_end=date(year, 12, 31),
    )


@pytest.mark.parametrize("window", [5, 7, 10])
def test_normalization_windows_calculate_mean_median_and_coverage(window):
    observations = tuple(
        _observation(year, str(value))
        for year, value in zip(range(2016, 2026), range(1, 11), strict=True)
    )
    result = analyze_historical_earnings(
        company_id=1,
        security_id=2,
        metric=EarningsMetric.NET_INCOME,
        observations=observations,
        window_years=window,
        method=NormalizationMethod.ARITHMETIC_MEAN,
        as_of=AS_OF,
    )
    values = list(range(11 - window, 11))
    assert result.status == EarningsResultStatus.AVAILABLE
    assert result.normalized_value == Decimal(sum(values)) / Decimal(window)
    expected_median = (
        Decimal(values[window // 2])
        if window % 2
        else Decimal(values[window // 2 - 1] + values[window // 2]) / Decimal(2)
    )
    assert result.median == expected_median
    assert result.valid_fiscal_years == window
    assert result.data_coverage == Decimal(1)
    assert result.confidence == EarningsConfidence.HIGH
    mean = Decimal(sum(values)) / Decimal(window)
    expected_deviation = (
        (
            sum(((Decimal(value) - mean) ** 2 for value in values), Decimal(0))
            / Decimal(window)
        )
        .sqrt()
        .quantize(Decimal("0.000000000001"))
    )
    assert result.standard_deviation == expected_deviation
    median_result = analyze_historical_earnings(
        company_id=1,
        security_id=None,
        metric=EarningsMetric.NET_INCOME,
        observations=observations,
        window_years=window,
        method=NormalizationMethod.MEDIAN,
        as_of=AS_OF,
    )
    assert median_result.normalized_value == result.median


def test_short_history_and_missing_fiscal_years_reduce_coverage_and_confidence():
    result = analyze_historical_earnings(
        company_id=1,
        security_id=None,
        metric=EarningsMetric.NET_INCOME,
        observations=(
            _observation(2022, "10"),
            _observation(2024, "0"),
            _observation(2025, "-5"),
        ),
        window_years=10,
        method=NormalizationMethod.MEDIAN,
        as_of=AS_OF,
    )
    assert result.status == EarningsResultStatus.AVAILABLE
    assert result.effective_window_years == 4
    assert result.data_coverage == Decimal("0.75")
    assert result.loss_making_years == 1
    assert result.normalized_value == Decimal("0")
    assert result.confidence == EarningsConfidence.MEDIUM
    assert result.peak_candidate_year == 2022
    assert result.trough_candidate_year == 2025
    assert any("exceptional-item" in assumption for assumption in result.assumptions)


def test_as_of_excludes_late_reported_and_future_fiscal_observations():
    late = _observation(2025, "500", available_at=AS_OF + timedelta(seconds=1))
    future_period = _observation(2027, "900")
    visible = _observation(2024, "30")
    result = analyze_historical_earnings(
        company_id=1,
        security_id=None,
        metric=EarningsMetric.NET_INCOME,
        observations=(visible, late, future_period),
        window_years=5,
        method=NormalizationMethod.ARITHMETIC_MEAN,
        as_of=AS_OF,
    )
    assert result.status == EarningsResultStatus.INSUFFICIENT_DATA
    assert result.status_reason is not None
    assert result.normalized_value is None
    assert result.fiscal_year_values == ((2024, Decimal("30")),)
    assert result.input_references == visible.references


def test_normalized_valuation_uses_existing_validity_and_status_rules():
    per_definition = next(
        item
        for item in default_metric_definitions()
        if item.metric_code == ValuationMetricCode.PER
    )
    ev_ebitda_definition = next(
        item
        for item in default_metric_definitions()
        if item.metric_code == ValuationMetricCode.EV_EBITDA
    )
    loss = calculate_metric(
        per_definition,
        ValuationInputs(
            security_id=1,
            observation_date=date(2026, 6, 1),
            as_of=AS_OF,
            currency="USD",
            closing_price=Decimal("100"),
            reported_eps=Decimal("0"),
        ),
    )
    assert loss.status == ValuationResultStatus.NOT_APPLICABLE
    unavailable = calculate_metric(
        ev_ebitda_definition,
        ValuationInputs(
            security_id=1,
            observation_date=date(2026, 6, 1),
            as_of=AS_OF,
            currency="USD",
            closing_price=Decimal("100"),
            shares_outstanding=Decimal("10"),
            short_term_debt=Decimal("1"),
            long_term_debt=Decimal("1"),
            cash_and_equivalents=Decimal("0"),
            operating_profit=Decimal("10"),
            depreciation_amortization=Decimal("-10"),
        ),
    )
    assert unavailable.status == ValuationResultStatus.NOT_APPLICABLE
    assert unavailable.value is None


class _Statements:
    def execute(self, *args, **kwargs):
        return []


class _Items:
    def get_by_code(self, _code):
        return None


class _Results:
    def __init__(self):
        self.saved = []

    def create(self, result):
        self.saved.append(result)
        return result


def test_empty_history_is_explicit_and_persists_all_metric_records():
    repository = _Results()
    calculator = CalculateNormalizedEarnings(_Statements(), _Items(), repository)
    results = calculator.execute(
        NormalizedEarningsRequest(
            company_id=1,
            as_of=AS_OF,
            window_years=5,
            method=NormalizationMethod.ARITHMETIC_MEAN,
        )
    )
    assert len(results) == 4
    assert all(
        result.status == EarningsResultStatus.INSUFFICIENT_DATA for result in results
    )
    assert all(
        result.normalized_valuation_status == ValuationResultStatus.INSUFFICIENT_DATA
        for result in results
        if result.metric in {EarningsMetric.EPS, EarningsMetric.EBITDA}
    )
    assert len(repository.saved) == 4


def test_normalized_per_and_ev_ebitda_reject_nonpositive_normalized_earnings():
    eps = analyze_historical_earnings(
        company_id=1,
        security_id=1,
        metric=EarningsMetric.EPS,
        observations=tuple(
            _observation(year, str(value))
            for year, value in zip((2022, 2023, 2024), (-3, -2, -1), strict=True)
        ),
        window_years=5,
        method=NormalizationMethod.MEDIAN,
        as_of=AS_OF,
    )
    ebitda = analyze_historical_earnings(
        company_id=1,
        security_id=1,
        metric=EarningsMetric.EBITDA,
        observations=tuple(_observation(year, "0") for year in (2022, 2023, 2024)),
        window_years=5,
        method=NormalizationMethod.MEDIAN,
        as_of=AS_OF,
    )
    inputs = ValuationInputs(
        security_id=1,
        observation_date=AS_OF.date(),
        as_of=AS_OF,
        currency="USD",
        closing_price=Decimal("100"),
        shares_outstanding=Decimal("10"),
        short_term_debt=Decimal("1"),
        long_term_debt=Decimal("2"),
        cash_and_equivalents=Decimal("0"),
    )
    request = NormalizedEarningsRequest(
        company_id=1,
        security_id=1,
        as_of=AS_OF,
        window_years=5,
        method=NormalizationMethod.MEDIAN,
        valuation_inputs=inputs,
    )
    results = CalculateNormalizedEarnings._calculate_normalized_valuations(
        [eps, ebitda], request
    )
    assert (
        results[0].normalized_valuation_status == ValuationResultStatus.NOT_APPLICABLE
    )
    assert results[0].normalized_valuation_value is None
    assert (
        results[1].normalized_valuation_status == ValuationResultStatus.NOT_APPLICABLE
    )
    assert results[1].normalized_valuation_value is None
