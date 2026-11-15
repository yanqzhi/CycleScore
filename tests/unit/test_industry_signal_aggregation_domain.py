"""Unit tests for provider-neutral signal aggregation policies and calculations."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from cyclescope.domain.entities.industry_signal import (
    IndustrySignalObservation,
    IndustrySignalType,
    IndustrySignalUnit,
)
from cyclescope.domain.entities.industry_signal_aggregate import (
    AggregateStatus,
    AggregationPolicyCode,
)
from cyclescope.domain.entities.region import (
    Region,
    RegionRelationship,
    RegionRelationshipType,
    RegionType,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.services.industry_signal_aggregation import (
    calculate_industry_signal_aggregate,
    resolve_aggregation_policy,
    validate_aggregation_region_scope,
)

AS_OF = datetime(2025, 4, 1, tzinfo=UTC)
POINT_DATE = date(2025, 3, 31)


def _obs(
    signal: IndustrySignalType = IndustrySignalType.INVENTORY,
    region: str = "JP",
    value: str = "10",
    *,
    source: int = 1,
    available: datetime = datetime(2025, 3, 31, tzinfo=UTC),
    revision: int = 1,
    unit: IndustrySignalUnit = IndustrySignalUnit.TONNE,
    currency: str | None = None,
    start: date | None = None,
    end: date | None = None,
    row_id: int = 1,
    observed: date | None = None,
    classification_version_id: int | None = None,
    classification_mapping_id: int | None = None,
) -> IndustrySignalObservation:
    point = signal not in {
        IndustrySignalType.PRODUCTION,
        IndustrySignalType.SHIPMENTS,
        IndustrySignalType.SALES,
        IndustrySignalType.ORDERS,
    }
    return IndustrySignalObservation(
        industry_id=1,
        source_id=source,
        signal_type=signal,
        region_code=region,
        unit_code=unit,
        value=Decimal(value),
        publication_date=available.date(),
        publication_datetime=available,
        available_at=available,
        collected_at=AS_OF,
        revision_number=revision,
        observation_date=(observed or POINT_DATE) if point else None,
        period_start=start if not point else None,
        period_end=end if not point else None,
        currency_code=currency,
        classification_version_id=classification_version_id,
        classification_mapping_id=classification_mapping_id,
        id=row_id,
    )


def _calculate(
    policy_code: AggregationPolicyCode,
    signal: IndustrySignalType,
    observations: tuple[IndustrySignalObservation, ...],
    *,
    codes: tuple[str, ...] = ("JP", "US"),
    expected: int | None = 2,
    unit: IndustrySignalUnit = IndustrySignalUnit.TONNE,
    currency: str | None = None,
    capacities: tuple[IndustrySignalObservation, ...] = (),
    source: int | None = 1,
    start: date | None = None,
    end: date | None = None,
):
    point = signal not in {
        IndustrySignalType.PRODUCTION,
        IndustrySignalType.SHIPMENTS,
        IndustrySignalType.SALES,
        IndustrySignalType.ORDERS,
    }
    policy = resolve_aggregation_policy(policy_code.value, 1, signal)
    return calculate_industry_signal_aggregate(
        policy=policy,
        observations=observations,
        capacity_observations=capacities,
        industry_id=1,
        sub_industry_id=None,
        aggregate_region_code="WORLD",
        constituent_region_codes=codes,
        unit_code=unit,
        currency_code=currency,
        observation_date=POINT_DATE if point else None,
        period_start=start if not point else None,
        period_end=end if not point else None,
        as_of=AS_OF,
        calculated_at=AS_OF,
        expected_contributor_count=expected,
        requested_source_id=source,
    )


def test_flow_sum_requires_exact_period_and_tracks_contributors() -> None:
    start, end = date(2025, 1, 1), date(2025, 3, 31)
    result = _calculate(
        AggregationPolicyCode.FLOW_SUM,
        IndustrySignalType.PRODUCTION,
        (
            _obs(IndustrySignalType.PRODUCTION, "JP", "10", start=start, end=end),
            _obs(
                IndustrySignalType.PRODUCTION,
                "US",
                "20",
                start=start,
                end=end,
                row_id=2,
            ),
        ),
        start=start,
        end=end,
    )
    assert result.value == Decimal("30.000000000000")
    assert result.status is AggregateStatus.AVAILABLE
    assert [item.observation_id for item in result.contributors] == [1, 2]


def test_pit_filtering_precedes_revision_validation_and_excludes_future_rows() -> None:
    visible = _obs(row_id=1)
    future = _obs(
        value="999",
        revision=2,
        available=datetime(2025, 4, 2, tzinfo=UTC),
        row_id=2,
    )
    result = _calculate(
        AggregationPolicyCode.INVENTORY_SUM,
        IndustrySignalType.INVENTORY,
        (visible, future),
        codes=("JP",),
        expected=1,
    )
    assert result.value == Decimal("10.000000000000")
    assert [item.observation_id for item in result.contributors] == [1]


@pytest.mark.parametrize(
    "rows, kwargs, message",
    [
        (
            (
                _obs(source=1),
                _obs(IndustrySignalType.INVENTORY, "US", source=2, row_id=2),
            ),
            {},
            "Source mixing",
        ),
        (
            (
                _obs(unit=IndustrySignalUnit.TONNE),
                _obs(
                    IndustrySignalType.INVENTORY,
                    "US",
                    unit=IndustrySignalUnit.UNIT,
                    row_id=2,
                ),
            ),
            {},
            "[Uu]nit or currency",
        ),
    ],
)
def test_incompatible_inputs_fail(rows, kwargs, message) -> None:
    with pytest.raises(DomainValidationError, match=message):
        _calculate(
            AggregationPolicyCode.INVENTORY_SUM,
            IndustrySignalType.INVENTORY,
            rows,
            **kwargs,
        )


def test_missing_value_and_unknown_expected_universe_are_not_zero_or_complete() -> None:
    missing = IndustrySignalObservation(
        industry_id=1,
        source_id=1,
        signal_type=IndustrySignalType.INVENTORY,
        region_code="JP",
        unit_code=IndustrySignalUnit.TONNE,
        value=None,
        missing_reason="Not reported",
        publication_date=POINT_DATE,
        publication_datetime=AS_OF,
        available_at=AS_OF,
        collected_at=AS_OF,
        revision_number=1,
        observation_date=POINT_DATE,
        id=8,
    )
    result = _calculate(
        AggregationPolicyCode.INVENTORY_SUM,
        IndustrySignalType.INVENTORY,
        (missing,),
        codes=("JP",),
        expected=None,
    )
    assert result.value is None
    assert result.status is AggregateStatus.INSUFFICIENT_DATA
    assert result.contributors[0].exclusion_reason == "Not reported"

    one = _calculate(
        AggregationPolicyCode.INVENTORY_SUM,
        IndustrySignalType.INVENTORY,
        (_obs(),),
        codes=("JP",),
        expected=None,
    )
    assert one.status is AggregateStatus.PARTIAL
    assert one.coverage_ratio is None


def test_explicit_coverage_threshold_and_source_are_retained() -> None:
    result = _calculate(
        AggregationPolicyCode.INVENTORY_SUM,
        IndustrySignalType.INVENTORY,
        (_obs(),),
        codes=("JP", "US"),
        expected=3,
        source=1,
    )
    assert result.status is AggregateStatus.INSUFFICIENT_DATA
    assert result.source_id == 1
    assert result.coverage_ratio == Decimal("0.3333333")

    empty = _calculate(
        AggregationPolicyCode.INVENTORY_SUM,
        IndustrySignalType.INVENTORY,
        (),
        codes=("JP",),
        expected=1,
        source=9,
    )
    assert empty.source_id == 9


def test_capacity_sum_uses_matching_reference_date() -> None:
    result = _calculate(
        AggregationPolicyCode.CAPACITY_SUM,
        IndustrySignalType.CAPACITY,
        (
            _obs(IndustrySignalType.CAPACITY, "JP", "100", row_id=1),
            _obs(IndustrySignalType.CAPACITY, "US", "200", row_id=2),
        ),
    )
    assert result.value == Decimal("300.000000000000")
    assert result.observation_date == POINT_DATE


def test_currency_and_classification_provenance_must_match() -> None:
    sales_rows = (
        _obs(
            IndustrySignalType.SALES,
            "JP",
            "100",
            unit=IndustrySignalUnit.CURRENCY,
            currency="JPY",
            start=date(2025, 1, 1),
            end=date(2025, 3, 31),
        ),
        _obs(
            IndustrySignalType.SALES,
            "US",
            "100",
            unit=IndustrySignalUnit.CURRENCY,
            currency="USD",
            start=date(2025, 1, 1),
            end=date(2025, 3, 31),
            row_id=2,
        ),
    )
    with pytest.raises(DomainValidationError, match="Unit or currency"):
        _calculate(
            AggregationPolicyCode.FLOW_SUM,
            IndustrySignalType.SALES,
            sales_rows,
            unit=IndustrySignalUnit.CURRENCY,
            currency="JPY",
            start=date(2025, 1, 1),
            end=date(2025, 3, 31),
        )

    classified = (
        _obs(classification_version_id=1, classification_mapping_id=11),
        _obs(
            IndustrySignalType.INVENTORY,
            "US",
            classification_version_id=2,
            classification_mapping_id=22,
            row_id=2,
        ),
    )
    with pytest.raises(DomainValidationError, match="Classification"):
        _calculate(
            AggregationPolicyCode.INVENTORY_SUM,
            IndustrySignalType.INVENTORY,
            classified,
        )


def test_period_and_observation_dates_are_not_mixed() -> None:
    wrong_period = _obs(
        IndustrySignalType.PRODUCTION,
        "JP",
        "10",
        start=date(2025, 2, 1),
        end=date(2025, 2, 28),
    )
    aligned_period = _obs(
        IndustrySignalType.PRODUCTION,
        "US",
        "20",
        start=date(2025, 1, 1),
        end=date(2025, 3, 31),
        row_id=2,
    )
    result = _calculate(
        AggregationPolicyCode.FLOW_SUM,
        IndustrySignalType.PRODUCTION,
        (wrong_period, aligned_period),
        start=date(2025, 1, 1),
        end=date(2025, 3, 31),
    )
    assert result.status is AggregateStatus.INSUFFICIENT_DATA
    assert result.value is None
    assert any("JP" in reason for reason in result.missing_reasons)

    wrong_point = _obs(
        IndustrySignalType.CAPACITY,
        "JP",
        "100",
        row_id=1,
        observed=date(2025, 3, 30),
    )
    result = _calculate(
        AggregationPolicyCode.CAPACITY_SUM,
        IndustrySignalType.CAPACITY,
        (wrong_point,),
        codes=("JP",),
        expected=1,
    )
    assert result.status is AggregateStatus.INSUFFICIENT_DATA
    assert any("JP" in reason for reason in result.missing_reasons)


def test_weighted_utilization_uses_capacity_not_arithmetic_mean() -> None:
    measures = (
        _obs(
            IndustrySignalType.CAPACITY_UTILIZATION,
            "JP",
            "50",
            unit=IndustrySignalUnit.PERCENTAGE,
            row_id=1,
        ),
        _obs(
            IndustrySignalType.CAPACITY_UTILIZATION,
            "US",
            "100",
            unit=IndustrySignalUnit.PERCENTAGE,
            row_id=2,
        ),
    )
    capacities = (
        _obs(IndustrySignalType.CAPACITY, "JP", "1", row_id=3),
        _obs(IndustrySignalType.CAPACITY, "US", "3", row_id=4),
    )
    result = _calculate(
        AggregationPolicyCode.CAPACITY_WEIGHTED_UTILIZATION,
        IndustrySignalType.CAPACITY_UTILIZATION,
        measures,
        unit=IndustrySignalUnit.PERCENTAGE,
        capacities=capacities,
    )
    assert result.value == Decimal("87.500000000000")
    assert len(result.contributors) == 4
    assert [c.role.value for c in result.contributors] == [
        "MEASURE",
        "CAPACITY_WEIGHT",
        "MEASURE",
        "CAPACITY_WEIGHT",
    ]


def test_missing_capacity_disables_weighted_utilization() -> None:
    utilization = _obs(
        IndustrySignalType.CAPACITY_UTILIZATION,
        unit=IndustrySignalUnit.PERCENTAGE,
    )
    result = _calculate(
        AggregationPolicyCode.CAPACITY_WEIGHTED_UTILIZATION,
        IndustrySignalType.CAPACITY_UTILIZATION,
        (utilization,),
        codes=("JP",),
        expected=1,
        unit=IndustrySignalUnit.PERCENTAGE,
    )
    assert result.status is AggregateStatus.INSUFFICIENT_DATA
    assert result.value is None


def test_region_scope_rejects_overlap_and_does_not_traverse_membership() -> None:
    world = Region("WORLD", "World", RegionType.GLOBAL, id=1)
    asia = Region("ASIA", "Asia", RegionType.CONTINENT, id=2)
    japan = Region("JP", "Japan", RegionType.COUNTRY, id=3)
    edges = (RegionRelationship(1, 2), RegionRelationship(2, 3))
    with pytest.raises(DomainValidationError, match="Non-overlap"):
        validate_aggregation_region_scope(world, (asia, japan), edges)
    validate_aggregation_region_scope(world, (japan,), edges)

    euro = Region("EURO", "Eurozone", RegionType.ECONOMIC_REGION, id=4)
    france = Region("FR", "France", RegionType.COUNTRY, id=5)
    member_edge = RegionRelationship(4, 5, RegionRelationshipType.MEMBER_OF)
    with pytest.raises(DomainValidationError, match="explicitly contained"):
        validate_aggregation_region_scope(world, (france,), (member_edge,))
    validate_aggregation_region_scope(euro, (france,), (member_edge,))


def test_policy_rejects_events_and_arbitrary_policy_version() -> None:
    with pytest.raises(DomainValidationError, match="does not support"):
        resolve_aggregation_policy(
            AggregationPolicyCode.FLOW_SUM.value,
            1,
            IndustrySignalType.CAPACITY_ADDITION,
        )
    with pytest.raises(DomainValidationError, match="version 1"):
        resolve_aggregation_policy(
            AggregationPolicyCode.INVENTORY_SUM.value,
            2,
            IndustrySignalType.INVENTORY,
        )
