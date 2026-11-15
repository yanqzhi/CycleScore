"""Domain tests for deterministic company-level inventory calculations."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from cyclescope.domain.entities.inventory import (
    InventoryAnnualObservation,
    InventoryConfidence,
    InventoryConfig,
    InventoryStatus,
    InventoryTrend,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.services.inventory import calculate_inventory

AS_OF = datetime(2026, 6, 1, tzinfo=UTC)


def _row(year: int, inventory: str | None, cogs: str | None = "100"):
    return InventoryAnnualObservation(
        fiscal_year=year,
        period_start=date(year, 4, 1),
        period_end=date(year + 1, 3, 31),
        currency="JPY",
        source_id=1,
        accounting_standard="JGAAP",
        consolidation_scope="CONSOLIDATED",
        closing_inventory=Decimal(inventory) if inventory is not None else None,
        cogs=Decimal(cogs) if cogs is not None else None,
        inventory_reference=None,
        cogs_reference=None,
    )


def _calculate(*rows, config=None):
    return calculate_inventory(
        company_id=1,
        security_id=None,
        as_of=AS_OF,
        observations=tuple(rows),
        config=config,
    )


def test_inventory_metrics_and_zero_denominator_boundaries() -> None:
    prior, current = _calculate(_row(2024, "0"), _row(2025, "20"))
    assert prior.closing_inventory == 0
    assert prior.inventory_growth is None
    assert prior.inventory_turnover is None
    assert prior.status == InventoryStatus.PARTIAL
    assert current.opening_inventory == 0
    assert current.inventory_change == 20
    assert current.inventory_growth is None
    assert current.average_inventory == 10
    assert current.inventory_turnover == 10
    assert current.dio == Decimal("36.5")
    assert "opening inventory is zero" in " ".join(current.unavailable_reasons)


def test_negative_inventory_and_nonpositive_cogs_are_not_accepted() -> None:
    snapshots = _calculate(
        _row(2023, "10"), _row(2024, "-2", "0"), _row(2025, "10", "-1")
    )
    assert snapshots[1].closing_inventory is None
    assert snapshots[1].inventory_turnover is None
    assert any("negative" in reason for reason in snapshots[1].unavailable_reasons)
    assert snapshots[2].cogs is None
    assert snapshots[2].trend == InventoryTrend.UNKNOWN
    assert any(
        "must be positive" in reason for reason in snapshots[2].unavailable_reasons
    )


def test_missing_fiscal_year_is_not_filled_or_used_as_opening() -> None:
    snapshots = _calculate(_row(2022, "10"), _row(2024, "30"))
    assert len(snapshots) == 2
    assert snapshots[1].opening_inventory is None
    assert snapshots[1].average_inventory is None
    assert snapshots[1].trend == InventoryTrend.UNKNOWN


def test_overlapping_fiscal_periods_do_not_supply_opening_inventory() -> None:
    previous = _row(2023, "10")
    current = InventoryAnnualObservation(
        fiscal_year=2024,
        period_start=date(2024, 1, 1),
        period_end=date(2025, 3, 31),
        currency="JPY",
        source_id=1,
        accounting_standard="JGAAP",
        consolidation_scope="CONSOLIDATED",
        closing_inventory=Decimal("20"),
        cogs=Decimal("100"),
        inventory_reference=None,
        cogs_reference=None,
    )
    snapshot = _calculate(previous, current)[1]
    assert snapshot.opening_inventory is None
    assert any("overlaps" in reason for reason in snapshot.unavailable_reasons)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (("100", "120", "150"), InventoryTrend.INCREASING),
        (("150", "120", "100"), InventoryTrend.DECREASING),
        (("100", "102", "104"), InventoryTrend.STABLE),
        (("100", "130", "110"), InventoryTrend.VOLATILE),
    ],
)
def test_trend_classification(values, expected) -> None:
    snapshots = _calculate(
        *(
            _row(year, value)
            for year, value in zip((2023, 2024, 2025), values, strict=True)
        )
    )
    assert snapshots[-1].trend == expected


def test_configuration_is_validated_and_snapshotted() -> None:
    with pytest.raises(DomainValidationError):
        InventoryConfig(days_per_year=360)
    config = InventoryConfig(
        version=2, stable_growth_threshold=Decimal("0.1"), minimum_trend_observations=4
    )
    result = _calculate(_row(2023, "10"), config=config)[0]
    assert result.config_snapshot == {
        "version": 2,
        "days_per_year": 365,
        "stable_growth_threshold": "0.1",
        "minimum_trend_observations": 4,
    }
    assert result.data_coverage == Decimal("0.125")


def test_invalid_latest_inventory_does_not_reuse_an_older_trend() -> None:
    snapshots = _calculate(
        _row(2021, "100"),
        _row(2022, "120"),
        _row(2023, "140"),
        _row(2024, "-1"),
    )
    assert snapshots[-1].trend == InventoryTrend.UNKNOWN


def test_large_decimal_inputs_are_calculated_without_float_conversion() -> None:
    result = _calculate(
        _row(2024, "1000000000000000000000000"), _row(2025, "2000000000000000000000000")
    )[-1]
    assert result.inventory_change == Decimal("1000000000000000000000000")
    assert result.average_inventory == Decimal("1500000000000000000000000")


def test_missing_inputs_remain_unavailable_and_confidence_reflects_coverage() -> None:
    first, second = _calculate(_row(2023, "10"), _row(2024, "20", None))
    assert first.cogs == Decimal("100")
    assert second.cogs is None
    assert second.inventory_turnover is None
    assert second.status == InventoryStatus.PARTIAL
    assert second.data_coverage == Decimal("0.625")
    assert second.confidence == InventoryConfidence.MEDIUM
    assert any("Missing annual COGS" in reason for reason in second.unavailable_reasons)
    assert first.confidence == InventoryConfidence.LOW


def test_identical_inputs_produce_deterministic_snapshots() -> None:
    rows = (_row(2023, "10"), _row(2024, "20"), _row(2025, "30"))
    assert _calculate(*rows) == _calculate(*rows)


def test_config_rejects_invalid_trend_threshold() -> None:
    with pytest.raises(DomainValidationError):
        InventoryConfig(stable_growth_threshold=Decimal("1"))
