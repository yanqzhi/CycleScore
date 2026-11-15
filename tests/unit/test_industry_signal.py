"""Domain validation tests for industry signal observations."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from cyclescope.domain.entities.industry_signal import (
    IndustrySignalObservation,
    IndustrySignalTemporalKind,
    IndustrySignalType,
    IndustrySignalUnit,
)
from cyclescope.domain.exceptions import DomainValidationError

NOW = datetime(2025, 3, 1, tzinfo=UTC)


def _observation(**overrides: object) -> IndustrySignalObservation:
    values: dict[str, object] = {
        "industry_id": 1,
        "source_id": 1,
        "signal_type": IndustrySignalType.INVENTORY,
        "region_code": "JP",
        "unit_code": IndustrySignalUnit.TONNE,
        "value": Decimal("120.5"),
        "observation_date": date(2025, 2, 28),
        "publication_date": date(2025, 3, 1),
        "publication_datetime": NOW,
        "available_at": NOW,
        "collected_at": NOW,
        "revision_number": 1,
    }
    values.update(overrides)
    return IndustrySignalObservation(**values)  # type: ignore[arg-type]


def test_valid_point_period_and_event_shapes_are_distinct() -> None:
    point = _observation()
    period = _observation(
        signal_type=IndustrySignalType.PRODUCTION,
        observation_date=None,
        period_start=date(2025, 2, 1),
        period_end=date(2025, 2, 28),
    )
    announced = _observation(
        signal_type=IndustrySignalType.CAPACITY_CLOSURE_ANNOUNCED,
        observation_date=date(2025, 2, 20),
    )
    completed = _observation(
        signal_type=IndustrySignalType.CAPACITY_CLOSURE_COMPLETED,
        observation_date=date(2025, 2, 20),
    )

    assert point.temporal_kind is IndustrySignalTemporalKind.POINT
    assert period.temporal_kind is IndustrySignalTemporalKind.PERIOD
    assert announced.temporal_kind is IndustrySignalTemporalKind.EVENT
    assert completed.temporal_kind is IndustrySignalTemporalKind.EVENT
    assert announced.signal_type is not completed.signal_type
    assert announced.observation_key != completed.observation_key


@pytest.mark.parametrize(
    "overrides",
    [
        {"industry_id": 0},
        {"source_id": 0},
        {"revision_number": 0},
        {"region_code": "jp"},
        {"region_code": " JP "},
        {"period_start": date(2025, 2, 1)},
        {
            "signal_type": IndustrySignalType.PRODUCTION,
            "observation_date": None,
        },
        {
            "signal_type": IndustrySignalType.PRODUCTION,
            "observation_date": None,
            "period_start": date(2025, 3, 1),
            "period_end": date(2025, 2, 1),
        },
        {"unit_code": IndustrySignalUnit.CURRENCY},
        {"currency_code": "JPY"},
        {"signal_type": "NOT_A_SIGNAL"},
        {"signal_type": IndustrySignalType.CAPACITY_UTILIZATION},
        {
            "signal_type": IndustrySignalType.CAPACITY_UTILIZATION,
            "unit_code": IndustrySignalUnit.PERCENTAGE,
            "value": Decimal("100.01"),
        },
        {"value": None},
        {"value": Decimal("1E+26")},
        {"available_at": datetime(2025, 3, 1)},
        {
            "publication_datetime": datetime(2025, 3, 2, tzinfo=UTC),
        },
    ],
)
def test_invalid_signal_inputs_are_rejected(overrides: dict[str, object]) -> None:
    with pytest.raises(DomainValidationError):
        _observation(**overrides)


def test_currency_signal_requires_and_preserves_currency() -> None:
    observation = _observation(
        signal_type=IndustrySignalType.SALES,
        unit_code=IndustrySignalUnit.CURRENCY,
        currency_code="JPY",
        period_start=date(2025, 2, 1),
        period_end=date(2025, 2, 28),
        observation_date=None,
    )
    assert observation.currency_code == "JPY"


def test_production_rejects_currency_unit_without_implicit_conversion() -> None:
    with pytest.raises(DomainValidationError, match="incompatible"):
        _observation(
            signal_type=IndustrySignalType.PRODUCTION,
            unit_code=IndustrySignalUnit.CURRENCY,
            currency_code="JPY",
            observation_date=None,
            period_start=date(2025, 2, 1),
            period_end=date(2025, 2, 28),
        )


def test_missing_value_requires_reason_and_never_becomes_zero() -> None:
    missing = _observation(value=None, missing_reason="Source did not report value.")
    assert missing.value is None
    assert missing.missing_reason == "Source did not report value."


def test_percentage_boundary_and_numeric_precision() -> None:
    utilization = _observation(
        signal_type=IndustrySignalType.CAPACITY_UTILIZATION,
        unit_code=IndustrySignalUnit.PERCENTAGE,
        value=Decimal("100"),
    )
    upper_precision = _observation(value=Decimal("1E+25"))
    assert utilization.value == Decimal("100")
    assert upper_precision.value == Decimal("1E+25")
