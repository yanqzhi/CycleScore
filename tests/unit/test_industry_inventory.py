"""Unit tests for industry inventory classification and numeric behavior."""

from datetime import date
from decimal import Decimal

import pytest

from cyclescope.domain.entities.industry_inventory import (
    IndustryInventoryClassification as Classification,
)
from cyclescope.domain.entities.industry_inventory import (
    IndustryInventoryConfig,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.services.industry_inventory import (
    _checked,
    _classify,
    _date_year_ago,
    _expected_interval,
    _ratio_change,
)


def _config() -> IndustryInventoryConfig:
    return IndustryInventoryConfig(
        version=1,
        accumulation_yoy=Decimal("0.05"),
        rapid_accumulation_yoy=Decimal("0.20"),
        normalization_prior_yoy=Decimal("-0.10"),
        normalization_growth_ceiling=Decimal("0.05"),
        stable_growth_tolerance=Decimal("0.02"),
        gap_ratio_tolerance=Decimal("0.02"),
        minimum_coverage=Decimal("0.80"),
        expected_observation_interval_months=12,
    )


def _classify_case(
    *,
    change: str | None,
    yoy: str | None,
    prior: str | None = None,
    acceleration: str | None = None,
    gap: str | None = None,
) -> Classification:
    return _classify(
        current_value=Decimal("100"),
        absolute_change=Decimal(change) if change is not None else None,
        yoy=Decimal(yoy) if yoy is not None else None,
        prior_yoy=Decimal(prior) if prior is not None else None,
        acceleration=(Decimal(acceleration) if acceleration is not None else None),
        gap=Decimal(gap) if gap is not None else None,
        config=_config(),
    )


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (
            {"change": "-10", "yoy": "-0.10", "gap": "-5"},
            Classification.DRAWDOWN,
        ),
        (
            {
                "change": "5",
                "yoy": "-0.03",
                "prior": "-0.20",
                "acceleration": "0.17",
                "gap": "0",
            },
            Classification.NORMALIZATION,
        ),
        (
            {"change": "20", "yoy": "0.25", "acceleration": "0.05", "gap": "5"},
            Classification.RAPID_ACCUMULATION,
        ),
        (
            {"change": "10", "yoy": "0.10", "acceleration": "-0.03", "gap": "0"},
            Classification.DECELERATING,
        ),
        (
            {"change": "10", "yoy": "0.10", "acceleration": "0.03", "gap": "0"},
            Classification.ACCUMULATION,
        ),
        (
            {"change": "10", "yoy": "0.01", "gap": None},
            Classification.UNKNOWN,
        ),
    ],
)
def test_classification_precedence_and_diagnostics(
    kwargs: dict[str, str | None], expected: Classification
) -> None:
    assert _classify_case(**kwargs) is expected


def test_exact_calendar_anniversary_does_not_substitute_for_leap_day() -> None:
    assert _date_year_ago(date(2024, 2, 29)) is None
    assert _date_year_ago(date(2025, 2, 28)) == date(2024, 2, 28)


def test_unconfigured_observation_interval_disables_adjacent_comparisons() -> None:
    config = IndustryInventoryConfig(
        version=1,
        accumulation_yoy=Decimal("0.05"),
        rapid_accumulation_yoy=Decimal("0.20"),
        normalization_prior_yoy=Decimal("-0.10"),
        normalization_growth_ceiling=Decimal("0.05"),
        stable_growth_tolerance=Decimal("0.02"),
        gap_ratio_tolerance=Decimal("0.02"),
        minimum_coverage=Decimal("0.80"),
    )
    assert config.expected_observation_interval_months is None


def test_zero_prior_year_inventory_is_invalid_for_yoy() -> None:
    with pytest.raises(DomainValidationError, match="zero"):
        _ratio_change(Decimal("10"), Decimal(0))


def test_numeric_boundary_rounds_once_and_rejects_overflow() -> None:
    assert _checked(Decimal("1.1234567890125")) == Decimal("1.123456789012")
    assert _checked(Decimal("99999999999999999999999999")) == Decimal(
        "99999999999999999999999999.000000000000"
    )
    with pytest.raises(DomainValidationError, match=r"NUMERIC\(38, 12\)"):
        _checked(Decimal("100000000000000000000000000"))


def test_configuration_rejects_inconsistent_thresholds() -> None:
    with pytest.raises(DomainValidationError, match="Rapid threshold"):
        IndustryInventoryConfig(
            version=1,
            normalization_prior_yoy=Decimal("-0.10"),
            normalization_growth_ceiling=Decimal("0.05"),
            stable_growth_tolerance=Decimal("0.02"),
            gap_ratio_tolerance=Decimal("0.02"),
            minimum_coverage=Decimal("0.80"),
            expected_observation_interval_months=12,
            accumulation_yoy=Decimal("0.20"),
            rapid_accumulation_yoy=Decimal("0.20"),
        )


@pytest.mark.parametrize(
    ("prior", "current", "months", "expected"),
    [
        # A missing monthly observation must not be treated as the adjacent month.
        (date(2025, 1, 31), date(2025, 3, 31), 1, False),
        # Same month delta with different non-month-end days is irregular.
        (date(2025, 1, 15), date(2025, 2, 28), 1, False),
        # Calendar quarter ends are comparable at the configured 3-month cadence.
        (date(2025, 3, 31), date(2025, 6, 30), 3, True),
        # A quarter with a missing month cannot be substituted.
        (date(2025, 3, 31), date(2025, 7, 31), 3, False),
        # Unknown cadence is conservatively unavailable.
        (date(2025, 6, 30), date(2025, 12, 31), None, False),
    ],
)
def test_observation_interval_policy(
    prior: date, current: date, months: int | None, expected: bool
) -> None:
    assert _expected_interval(prior, current, months) is expected


@pytest.mark.parametrize(
    "overrides",
    [
        {"normalization_prior_yoy": Decimal("0")},
        {"normalization_growth_ceiling": Decimal("0.06")},
        {"accumulation_yoy": Decimal("-0.01")},
        {"expected_observation_interval_months": 2},
        {"gap_ratio_tolerance": Decimal("1.01")},
    ],
)
def test_configuration_rejects_invalid_boundaries(
    overrides: dict[str, Decimal | int],
) -> None:
    values: dict[str, Decimal | int] = {
        "version": 1,
        "accumulation_yoy": Decimal("0.05"),
        "rapid_accumulation_yoy": Decimal("0.20"),
        "normalization_prior_yoy": Decimal("-0.10"),
        "normalization_growth_ceiling": Decimal("0.05"),
        "stable_growth_tolerance": Decimal("0.02"),
        "gap_ratio_tolerance": Decimal("0.02"),
        "minimum_coverage": Decimal("0.80"),
        "expected_observation_interval_months": 12,
    }
    values.update(overrides)
    with pytest.raises(DomainValidationError):
        IndustryInventoryConfig(**values)  # type: ignore[arg-type]
