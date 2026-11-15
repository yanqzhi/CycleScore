"""Domain tests for cycle direction, confidence, and configuration rules."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from cyclescope.domain.entities.cycle_score import (
    CyclePhase,
    CycleScoreComponentCode,
    CycleScoreConfidence,
    CycleScoreConfig,
    CycleScoreInputReference,
    CycleScoreObservation,
    CycleScoreStatus,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.services.cycle_score import analyze_cycle_score

AS_OF = datetime(2026, 12, 31, tzinfo=UTC)


def _observations(values, years=None):
    years = years or tuple(range(2026 - len(values), 2026))
    results = []
    for index, (year, value) in enumerate(zip(years, values, strict=True), 1):
        end = date(year, 12, 31)
        reference = CycleScoreInputReference(
            record_id=index,
            statement_id=index,
            normalized_earnings_result_id=99,
            source_id=7,
            revision_number=1,
            fiscal_year=year,
            fiscal_period="FY",
            item_code="OPERATING_PROFIT",
            period_end=end,
            available_at=datetime(year + 1, 2, 1, tzinfo=UTC),
        )
        results.append(
            CycleScoreObservation(
                fiscal_year=year,
                value=Decimal(value),
                currency="USD",
                source_id=7,
                calculation_version=1,
                period_start=date(year, 1, 1),
                period_end=end,
                references=(reference,),
            )
        )
    return tuple(results)


def _calculate(values, years=None, *, config=None):
    observations = _observations(values, years)
    return analyze_cycle_score(
        company_id=10,
        security_id=20,
        as_of=AS_OF,
        observations=observations,
        window_start_fiscal_year=years[0] if years else observations[0].fiscal_year,
        window_end_fiscal_year=years[-1] if years else observations[-1].fiscal_year,
        currency="USD",
        source_id=7,
        normalized_earnings_result_id=99,
        config=config or CycleScoreConfig(window_years=7),
    )


def test_expansion_and_improvement_on_negative_earnings_are_supported() -> None:
    expansion = _calculate(("10", "20", "30", "40", "50"))
    assert expansion.phase == CyclePhase.EXPANSION
    assert expansion.status.value == "AVAILABLE"
    assert expansion.score is not None and expansion.score > 50
    momentum = next(
        item
        for item in expansion.components
        if item.code == CycleScoreComponentCode.EARNINGS_MOMENTUM
    )
    assert momentum.value is not None and momentum.value > 0

    negative_improving = _calculate(("-20", "-100", "-200", "-180", "-170"))
    assert negative_improving.phase == CyclePhase.EARLY_RECOVERY


def test_negative_and_zero_trends_do_not_use_percentage_growth() -> None:
    falling = _calculate(("-10", "-20", "-30", "-40", "-50"))
    assert falling.phase == CyclePhase.CONTRACTION
    zero_to_positive = _calculate(("0", "0", "10", "20", "30"))
    assert zero_to_positive.phase == CyclePhase.EXPANSION
    assert zero_to_positive.score is not None


def test_peak_and_contraction_require_direction_not_level_alone() -> None:
    peak = _calculate(("0", "100", "200", "190", "150"))
    assert peak.phase == CyclePhase.PEAK
    acceleration = next(
        item
        for item in peak.components
        if item.code == CycleScoreComponentCode.EARNINGS_ACCELERATION
    )
    assert acceleration.value is not None and acceleration.value < 0
    low_and_falling = _calculate(("100", "50", "20", "10", "0"))
    assert low_and_falling.phase == CyclePhase.CONTRACTION
    assert "does not confirm a trough" in low_and_falling.phase_reason


def test_trough_requires_recent_stabilization_and_positive_acceleration() -> None:
    trough = _calculate(("100", "50", "20", "21", "22"))
    assert trough.phase == CyclePhase.TROUGH
    recovery = _calculate(("300", "150", "20", "40", "70"))
    assert recovery.phase == CyclePhase.EARLY_RECOVERY


def test_flat_or_conflicting_signals_are_unknown_and_partial() -> None:
    result = _calculate(("10", "10", "10", "10", "10"))
    assert result.phase == CyclePhase.UNKNOWN
    assert result.status.value == "PARTIAL"
    assert result.score is not None
    assert result.confidence == CycleScoreConfidence.LOW
    position = next(
        item
        for item in result.components
        if item.code == CycleScoreComponentCode.HISTORICAL_POSITION
    )
    assert position.score == Decimal("50.0000000")
    assert "unknown" in (position.reason or "")
    conflicting = _calculate(("200", "100", "20", "100", "120"))
    assert conflicting.phase == CyclePhase.UNKNOWN
    assert "conflicts" in conflicting.phase_reason


def test_missing_fiscal_years_are_not_filled_and_reduce_coverage() -> None:
    years = (2020, 2021, 2023, 2024, 2025)
    result = _calculate(("10", "20", "30", "40", "50"), years)
    assert result.coverage == Decimal("0.8333333")
    assert len(result.input_references) == 5
    assert {reference.fiscal_year for reference in result.input_references} == set(
        years
    )


def test_insufficient_history_has_no_score_and_keeps_known_coverage() -> None:
    observations = _observations(("1", "2", "3", "4"))
    result = analyze_cycle_score(
        company_id=10,
        security_id=None,
        as_of=AS_OF,
        observations=observations,
        window_start_fiscal_year=2021,
        window_end_fiscal_year=2025,
        currency="USD",
        source_id=7,
        normalized_earnings_result_id=99,
        config=CycleScoreConfig(window_years=5),
    )
    assert result.status == CycleScoreStatus.INSUFFICIENT_DATA
    assert result.phase == CyclePhase.UNKNOWN
    assert result.score is None
    assert result.coverage == Decimal("0.8")
    assert all(component.score is None for component in result.components)


def test_confidence_thresholds_and_decimal_calculation_are_deterministic() -> None:
    seven = _calculate(
        tuple(str(n * n) for n in range(1, 8)), config=CycleScoreConfig()
    )
    assert seven.confidence == CycleScoreConfidence.HIGH
    same = _calculate(tuple(str(n * n) for n in range(1, 8)), config=CycleScoreConfig())
    assert seven == same

    low_config = replace(
        CycleScoreConfig(window_years=7),
        medium_confidence_coverage=Decimal("0.9"),
        high_confidence_coverage=Decimal("0.95"),
    )
    low = _calculate(
        ("1", "2", "3", "4", "5"), (2019, 2020, 2022, 2023, 2024), config=low_config
    )
    assert low.confidence == CycleScoreConfidence.LOW


def test_future_input_references_and_incompatible_sources_are_fatal() -> None:
    observations = list(_observations(("1", "2", "3", "4", "5")))
    observations[0] = replace(
        observations[0],
        references=(
            replace(
                observations[0].references[0], available_at=AS_OF + timedelta(days=1)
            ),
        ),
    )
    with pytest.raises(DomainValidationError, match="not eligible"):
        analyze_cycle_score(
            company_id=10,
            security_id=None,
            as_of=AS_OF,
            observations=tuple(observations),
            window_start_fiscal_year=2021,
            window_end_fiscal_year=2025,
            currency="USD",
            source_id=7,
            normalized_earnings_result_id=99,
            config=CycleScoreConfig(window_years=5),
        )
    mixed = replace(observations[1], source_id=8)
    with pytest.raises(DomainValidationError, match="mix incompatible"):
        analyze_cycle_score(
            company_id=10,
            security_id=None,
            as_of=AS_OF,
            observations=tuple((*observations[:1], mixed, *observations[2:])),
            window_start_fiscal_year=2021,
            window_end_fiscal_year=2025,
            currency="USD",
            source_id=None,
            normalized_earnings_result_id=99,
            config=CycleScoreConfig(window_years=5),
        )


def test_configuration_rejects_invalid_weights_and_thresholds() -> None:
    with pytest.raises(DomainValidationError, match="total exactly 1"):
        CycleScoreConfig(
            weights=tuple(
                (code, weight / Decimal(2))
                for code, weight in CycleScoreConfig().weights
            )
        )
    with pytest.raises(DomainValidationError, match="Phase scores"):
        CycleScoreConfig(phase_scores=CycleScoreConfig().phase_scores[:-1])
    with pytest.raises(DomainValidationError, match="deadbands"):
        CycleScoreConfig(momentum_deadband=Decimal("0.2"))
