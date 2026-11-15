"""Domain tests for Industry Supply & Demand compatibility and rules."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from cyclescope.domain.entities.industry_inventory import (
    IndustryInventoryClassification,
    IndustryInventoryConfig,
    IndustryInventoryInputReference,
    IndustryInventorySnapshot,
    IndustryInventoryStatus,
    IndustryInventoryTrend,
)
from cyclescope.domain.entities.industry_signal import (
    IndustrySignalTemporalKind,
    IndustrySignalType,
    IndustrySignalUnit,
)
from cyclescope.domain.entities.industry_signal_aggregate import (
    AggregateInputRole,
    AggregateScopeRole,
    AggregateStatus,
    AggregationOperation,
    AggregationPolicyCode,
    IndustrySignalAggregateContributor,
    IndustrySignalAggregateScope,
    IndustrySignalAggregateSnapshot,
)
from cyclescope.domain.entities.industry_supply_demand import (
    IndustrySupplyDemandConfig,
    IndustrySupplyDemandPhase,
    IndustrySupplyDemandSnapshot,
    IndustrySupplyDemandStatus,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.services.industry_supply_demand import (
    _phase,
    calculate_industry_supply_demand,
)

CUTOFF = datetime(2026, 2, 1, tzinfo=UTC)
SCOPE = ((2, "JP"),)


def _config(**overrides: Decimal) -> IndustrySupplyDemandConfig:
    values: dict[str, Decimal | int] = {
        "version": 1,
        "minimum_coverage": Decimal("0.80"),
        "flow_gap_tolerance": Decimal("0.10"),
        "strong_demand_growth": Decimal("0.10"),
        "negative_demand_growth": Decimal("-0.05"),
        "inventory_accumulation_yoy": Decimal("0.10"),
        "inventory_drawdown_yoy": Decimal("-0.10"),
        "minimum_evidence_coverage": Decimal("0.50"),
    }
    values.update(overrides)
    return IndustrySupplyDemandConfig(**values)  # type: ignore[arg-type]


def _aggregate(
    *,
    signal: IndustrySignalType,
    start: date,
    end: date,
    value: str,
    identity: int,
    as_of: datetime = CUTOFF,
    region_code: str = "JP",
    policy_version: int = 1,
    calculation_version: int = 1,
    source_id: int = 1,
    unit: IndustrySignalUnit = IndustrySignalUnit.TONNE,
    currency: str | None = None,
    classification_version: int | None = None,
    classification_mapping: int | None = None,
) -> IndustrySignalAggregateSnapshot:
    contributor = IndustrySignalAggregateContributor(
        observation_id=identity,
        source_id=source_id,
        revision_number=1,
        region_code=region_code,
        observation_date=None,
        period_start=start,
        period_end=end,
        publication_date=end,
        publication_datetime=as_of,
        available_at=as_of,
        collected_at=as_of,
        source_reference=f"r-{identity}",
        role=AggregateInputRole.MEASURE,
        value=Decimal(value),
        unit_code=unit,
        currency_code=currency,
        classification_version_id=classification_version,
        classification_mapping_id=classification_mapping,
        included=True,
    )
    return IndustrySignalAggregateSnapshot(
        industry_id=1,
        sub_industry_id=None,
        signal_type=signal,
        temporal_kind=IndustrySignalTemporalKind.PERIOD,
        aggregate_region_code="WORLD",
        aggregate_region_id=1,
        requested_scopes=(
            IndustrySignalAggregateScope(1, "WORLD", AggregateScopeRole.AGGREGATE),
            IndustrySignalAggregateScope(2, "JP", AggregateScopeRole.CONSTITUENT),
        ),
        scope_complete=True,
        source_id=source_id,
        unit_code=unit,
        currency_code=currency,
        observation_date=None,
        period_start=start,
        period_end=end,
        as_of=as_of,
        calculated_at=as_of,
        policy_code=AggregationPolicyCode.FLOW_SUM,
        policy_version=policy_version,
        calculation_version=calculation_version,
        operation=AggregationOperation.SUM,
        minimum_coverage=Decimal("0.80"),
        value=Decimal(value),
        status=AggregateStatus.AVAILABLE,
        expected_contributor_count=1,
        actual_contributor_count=1,
        coverage_ratio=Decimal("1.0000000"),
        confidence=None,
        missing_reasons=(),
        validation_warnings=(),
        contributors=(contributor,),
        id=identity,
    )


def _flows(
    *,
    production: str = "50",
    shipments: str = "40",
    prior_production: str = "45",
    prior_shipments: str = "40",
    shipment_start: date = date(2024, 12, 1),
    prior_shipment_end: date = date(2024, 12, 31),
    current_start: date = date(2025, 12, 1),
    current_end: date = date(2025, 12, 31),
) -> tuple[IndustrySignalAggregateSnapshot, ...]:
    return (
        _aggregate(
            signal=IndustrySignalType.PRODUCTION,
            start=current_start,
            end=current_end,
            value=production,
            identity=101,
        ),
        _aggregate(
            signal=IndustrySignalType.SHIPMENTS,
            start=current_start,
            end=current_end,
            value=shipments,
            identity=102,
        ),
        _aggregate(
            signal=IndustrySignalType.PRODUCTION,
            start=shipment_start,
            end=prior_shipment_end,
            value=prior_production,
            identity=103,
        ),
        _aggregate(
            signal=IndustrySignalType.SHIPMENTS,
            start=shipment_start,
            end=prior_shipment_end,
            value=prior_shipments,
            identity=104,
        ),
    )


def _inventory(
    flows: tuple[IndustrySignalAggregateSnapshot, ...],
    *,
    classification: IndustryInventoryClassification = (
        IndustryInventoryClassification.DRAWDOWN
    ),
    yoy: Decimal = Decimal("-0.15"),
) -> IndustryInventorySnapshot:
    production, shipments = flows[0], flows[1]
    refs = tuple(
        IndustryInventoryInputReference(
            aggregate_id=row.id or 0,
            role=role,
            observation_date=None,
            period_start=row.period_start,
            period_end=row.period_end,
            source_id=row.source_id,
            available_at=row.as_of,
            contributor_revisions=((row.id or 1, row.source_id or 1, 1),),
            contributing_regions=SCOPE,
            coverage=Decimal("1.0000000"),
        )
        for row, role in ((production, "PRODUCTION"), (shipments, "SHIPMENTS"))
    )
    return IndustryInventorySnapshot(
        industry_id=1,
        sub_industry_id=None,
        aggregate_region_code="WORLD",
        source_id=1,
        unit_code="TONNE",
        currency_code=None,
        observation_date=date(2025, 12, 31),
        as_of=CUTOFF,
        calculated_at=CUTOFF,
        classification=classification,
        trend=IndustryInventoryTrend.DECREASING,
        status=IndustryInventoryStatus.AVAILABLE,
        inventory_value=Decimal(100),
        prior_inventory_value=Decimal(120),
        absolute_change=Decimal(-20),
        yoy_growth=yoy,
        prior_yoy_growth=None,
        growth_acceleration=None,
        production_value=Decimal(production.value or 0),
        shipments_value=Decimal(shipments.value or 0),
        production_shipment_gap=Decimal(production.value or 0)
        - Decimal(shipments.value or 0),
        coverage=Decimal("1.0000000"),
        confidence=Decimal("0.9000000"),
        config=IndustryInventoryConfig(
            version=1,
            accumulation_yoy=Decimal("0.05"),
            rapid_accumulation_yoy=Decimal("0.20"),
            normalization_prior_yoy=Decimal("-0.10"),
            normalization_growth_ceiling=Decimal("0.05"),
            stable_growth_tolerance=Decimal("0.02"),
            gap_ratio_tolerance=Decimal("0.02"),
            minimum_coverage=Decimal("0.80"),
        ),
        requested_scope=SCOPE,
        contributing_regions=SCOPE,
        input_references=refs,
        unavailable_reasons=(),
        id=201,
    )


def _calculate(
    flows: tuple[IndustrySignalAggregateSnapshot, ...] | None = None,
    inventory: IndustryInventorySnapshot | None = None,
    *,
    config: IndustrySupplyDemandConfig | None = None,
    source_id: int | None = None,
    scope: tuple[tuple[int, str], ...] = SCOPE,
) -> IndustrySupplyDemandSnapshot:
    rows = flows or _flows()
    inventories = (inventory,) if inventory is not None else ()
    return calculate_industry_supply_demand(
        aggregates=rows,
        inventories=inventories,
        industry_id=1,
        sub_industry_id=None,
        aggregate_region_id=1,
        aggregate_region_code="WORLD",
        requested_scope=scope,
        as_of=CUTOFF,
        calculated_at=CUTOFF,
        config=config or _config(flow_gap_tolerance=Decimal("0.25")),
        source_id=source_id,
    )


def test_current_flow_gap_growth_and_inventory_context_are_calculated() -> None:
    flows = _flows()
    result = _calculate(flows, _inventory(flows))
    assert result.flow_gap == Decimal("10.000000000000")
    assert result.flow_gap_ratio == Decimal("0.250000000000")
    assert result.shipment_growth_yoy == Decimal("0.000000000000")
    assert result.inventory_snapshot_id == 201
    assert result.inventory_classification is IndustryInventoryClassification.DRAWDOWN
    assert result.status is IndustrySupplyDemandStatus.AVAILABLE
    recovery = _calculate(
        flows,
        _inventory(flows),
        config=_config(
            flow_gap_tolerance=Decimal("0.25"),
            strong_demand_growth=Decimal(0),
        ),
    )
    assert recovery.phase is IndustrySupplyDemandPhase.DEMAND_RECOVERY
    assert result.confidence is None


@pytest.mark.parametrize("shipments", ["0", "-10"])
def test_nonpositive_current_shipments_make_gap_ratio_unavailable(
    shipments: str,
) -> None:
    flows = _flows(shipments=shipments)
    result = _calculate(flows, _inventory(flows))
    assert result.flow_gap is not None
    assert result.flow_gap_ratio is None
    assert result.status is IndustrySupplyDemandStatus.PARTIAL
    assert result.phase is IndustrySupplyDemandPhase.UNKNOWN
    assert any("current shipments" in reason for reason in result.unavailable_reasons)


@pytest.mark.parametrize("prior_shipments", ["0", "-1"])
def test_nonpositive_prior_year_shipments_make_yoy_unavailable(
    prior_shipments: str,
) -> None:
    flows = _flows(prior_shipments=prior_shipments)
    result = _calculate(flows, _inventory(flows))
    assert result.shipment_growth_yoy is None
    assert result.status is IndustrySupplyDemandStatus.PARTIAL
    assert any(
        "prior-year shipments" in reason for reason in result.unavailable_reasons
    )


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        # Oversupply requires strict positive gap and independent corroboration.
        (
            {
                "gap_ratio": Decimal("0.11"),
                "shipment_growth": Decimal("0"),
                "inventory_yoy": Decimal("0.10"),
                "inventory_classification": None,
            },
            IndustrySupplyDemandPhase.OVERSUPPLY,
        ),
        (
            {
                "gap_ratio": Decimal("0.10"),
                "shipment_growth": Decimal("-0.50"),
                "inventory_yoy": None,
                "inventory_classification": None,
            },
            IndustrySupplyDemandPhase.DEMAND_SLOWDOWN,
        ),
        (
            {
                "gap_ratio": Decimal("0.11"),
                "shipment_growth": Decimal("0"),
                "inventory_yoy": None,
                "inventory_classification": None,
            },
            IndustrySupplyDemandPhase.UNKNOWN,
        ),
        (
            {
                "gap_ratio": Decimal("-0.11"),
                "shipment_growth": Decimal("0.10"),
                "inventory_yoy": None,
                "inventory_classification": None,
            },
            IndustrySupplyDemandPhase.UNDERSUPPLY,
        ),
        (
            {
                "gap_ratio": Decimal("-0.10"),
                "shipment_growth": Decimal("0.10"),
                "inventory_yoy": Decimal("-0.10"),
                "inventory_classification": IndustryInventoryClassification.DRAWDOWN,
            },
            IndustrySupplyDemandPhase.DEMAND_RECOVERY,
        ),
        (
            {
                "gap_ratio": Decimal("0"),
                "shipment_growth": Decimal("0.10"),
                "inventory_yoy": Decimal("0"),
                "inventory_classification": (
                    IndustryInventoryClassification.ACCUMULATION
                ),
            },
            IndustrySupplyDemandPhase.EXPANSION,
        ),
        (
            {
                "gap_ratio": Decimal("0"),
                "shipment_growth": Decimal("0"),
                "inventory_yoy": Decimal("0"),
                "inventory_classification": (
                    IndustryInventoryClassification.ACCUMULATION
                ),
            },
            IndustrySupplyDemandPhase.BALANCED,
        ),
        (
            {
                "gap_ratio": Decimal("0"),
                "shipment_growth": Decimal("-0.05"),
                "inventory_yoy": None,
                "inventory_classification": None,
            },
            IndustrySupplyDemandPhase.DEMAND_SLOWDOWN,
        ),
    ],
)
def test_phase_precedence_and_threshold_boundaries(
    kwargs: dict[str, object], expected: IndustrySupplyDemandPhase
) -> None:
    assert (
        _phase(
            **kwargs,
            evidence_coverage=Decimal(1),
            config=_config(),
        )
        is expected
    )


def test_threshold_equality_does_not_create_gap_phase_without_corroboration() -> None:
    assert (
        _phase(
            gap_ratio=Decimal("0.10"),
            shipment_growth=Decimal(0),
            inventory_yoy=None,
            inventory_classification=None,
            evidence_coverage=Decimal(1),
            config=_config(),
        )
        is IndustrySupplyDemandPhase.UNKNOWN
    )


def test_incompatible_actual_region_pair_is_excluded() -> None:
    flows = _flows()
    expanded_scope = ((2, "JP"), (3, "US"))
    expanded_scopes = (
        IndustrySignalAggregateScope(1, "WORLD", AggregateScopeRole.AGGREGATE),
        IndustrySignalAggregateScope(2, "JP", AggregateScopeRole.CONSTITUENT),
        IndustrySignalAggregateScope(3, "US", AggregateScopeRole.CONSTITUENT),
    )
    adjusted = tuple(replace(row, requested_scopes=expanded_scopes) for row in flows)
    shipment = replace(
        adjusted[1],
        contributors=(replace(flows[1].contributors[0], region_code="US"),),
    )
    prior_shipment = replace(
        adjusted[3],
        contributors=(replace(flows[3].contributors[0], region_code="US"),),
    )
    result = _calculate(
        (adjusted[0], shipment, adjusted[2], prior_shipment), scope=expanded_scope
    )
    assert result.status is IndustrySupplyDemandStatus.INSUFFICIENT_DATA
    assert result.phase is IndustrySupplyDemandPhase.UNKNOWN
    assert any(not ref.included for ref in result.input_references)


def test_prior_year_pair_requires_exact_anniversary_and_duration() -> None:
    flows = _flows(prior_shipment_end=date(2024, 12, 30))
    result = _calculate(flows)
    assert result.shipment_growth_yoy is None
    assert any("prior-year" in reason for reason in result.unavailable_reasons)


@pytest.mark.parametrize(
    "mismatch",
    ["source", "unit", "currency", "classification", "policy", "calculation"],
)
def test_flow_pair_rejects_incompatible_cohort_metadata(mismatch: str) -> None:
    production, shipments = _flows()[:2]
    contributor = shipments.contributors[0]
    changes: dict[str, object] = {}
    contributor_changes: dict[str, object] = {}
    if mismatch == "source":
        changes["source_id"] = 2
        contributor_changes["source_id"] = 2
    elif mismatch == "unit":
        changes["unit_code"] = IndustrySignalUnit.UNIT
        contributor_changes["unit_code"] = IndustrySignalUnit.UNIT
    elif mismatch == "currency":
        changes.update(
            unit_code=IndustrySignalUnit.CURRENCY,
            currency_code="USD",
        )
        contributor_changes.update(
            unit_code=IndustrySignalUnit.CURRENCY,
            currency_code="USD",
        )
    elif mismatch == "classification":
        changes["contributors"] = (
            replace(
                contributor,
                classification_version_id=1,
                classification_mapping_id=1,
            ),
        )
        contributor = changes["contributors"][0]  # type: ignore[assignment]
    elif mismatch == "policy":
        changes["policy_version"] = 2
    else:
        changes["calculation_version"] = 2
    if contributor_changes:
        changes["contributors"] = (replace(contributor, **contributor_changes),)
    mismatched_shipments = replace(shipments, **changes)
    result = _calculate((production, mismatched_shipments))
    assert result.status is IndustrySupplyDemandStatus.INSUFFICIENT_DATA
    assert result.phase is IndustrySupplyDemandPhase.UNKNOWN
    assert any(not ref.included for ref in result.input_references)


def test_requested_scope_mismatch_does_not_form_a_pair() -> None:
    production, shipments = _flows()[:2]
    mismatched = replace(
        shipments,
        requested_scopes=(
            shipments.requested_scopes[0],
            replace(shipments.requested_scopes[1], region_code="US"),
        ),
        contributors=(replace(shipments.contributors[0], region_code="US"),),
    )
    result = _calculate((production, mismatched))
    assert result.status is IndustrySupplyDemandStatus.INSUFFICIENT_DATA
    assert result.production_value is None
    assert any(
        "Requested constituent scope" in (ref.exclusion_reason or "")
        for ref in result.input_references
        if not ref.included
    )


def test_future_aggregate_and_contributor_availability_are_not_selected() -> None:
    future_flows = tuple(
        replace(
            row,
            as_of=datetime(2026, 3, 1, tzinfo=UTC),
            calculated_at=datetime(2026, 3, 1, tzinfo=UTC),
            contributors=(
                replace(
                    row.contributors[0],
                    available_at=datetime(2026, 3, 1, tzinfo=UTC),
                    collected_at=datetime(2026, 3, 1, tzinfo=UTC),
                    publication_datetime=datetime(2026, 3, 1, tzinfo=UTC),
                ),
            ),
        )
        for row in _flows()[:2]
    )
    result = _calculate(future_flows)
    assert result.status is IndustrySupplyDemandStatus.INSUFFICIENT_DATA
    assert result.production_value is None
    assert all(ref.available_at <= CUTOFF for ref in result.input_references)


def test_latest_snapshot_is_selected_by_as_of_then_id() -> None:
    flows = _flows()
    later_as_of = replace(
        flows[0],
        id=105,
        value=Decimal("60"),
        contributors=(replace(flows[0].contributors[0], value=Decimal("60")),),
    )
    result = _calculate((flows[0], later_as_of, *flows[1:]))
    assert result.production_value == Decimal("60")
    selected = next(
        ref for ref in result.input_references if ref.role == "CURRENT_PRODUCTION"
    )
    assert selected.aggregate_id == 105


def test_inventory_nearest_date_is_not_substituted() -> None:
    flows = _flows()
    inventory = replace(_inventory(flows), observation_date=date(2025, 12, 30))
    result = _calculate(flows, inventory)
    assert result.inventory_snapshot_id is None
    assert result.status is IndustrySupplyDemandStatus.PARTIAL
    assert any(
        "date" in (ref.exclusion_reason or "")
        for ref in result.input_references
        if not ref.included
    )


def test_inventory_must_reference_the_exact_current_flow_ids() -> None:
    flows = _flows()
    inventory = _inventory(flows)
    wrong_refs = tuple(
        replace(ref, aggregate_id=(ref.aggregate_id or 0) + 900)
        for ref in inventory.input_references
    )
    result = _calculate(flows, replace(inventory, input_references=wrong_refs))
    assert result.inventory_snapshot_id is None
    assert result.status is IndustrySupplyDemandStatus.PARTIAL
    assert any(
        "exact selected flow aggregate IDs" in ref.exclusion_reason
        for ref in result.input_references
        if not ref.included
    )


def test_source_ambiguity_is_rejected_and_explicit_source_isolated() -> None:
    flows = _flows()
    other_source = tuple(
        replace(
            row,
            source_id=2,
            contributors=(replace(row.contributors[0], source_id=2),),
            id=(row.id or 0) + 1000,
        )
        for row in flows
    )
    with pytest.raises(DomainValidationError, match="Multiple eligible source"):
        _calculate(flows + other_source)
    result = _calculate(flows + other_source, source_id=1)
    assert result.source_id == 1
    assert all(ref.source_id == 1 for ref in result.input_references if ref.included)


def test_decimal_output_rounding_and_overflow() -> None:
    rounded_flows = _flows(production="10.0000000000005", shipments="0")
    rounded = _calculate(rounded_flows)
    assert rounded.flow_gap == Decimal("10.000000000000")
    overflow_flows = _flows(production="100000000000000000000000001", shipments="1")
    with pytest.raises(DomainValidationError, match=r"NUMERIC\(38, 12\)"):
        _calculate(overflow_flows)


@pytest.mark.parametrize(
    "overrides",
    [
        {"minimum_coverage": Decimal("1.1")},
        {"flow_gap_tolerance": Decimal("-0.1")},
        {"strong_demand_growth": Decimal("-0.1")},
        {"negative_demand_growth": Decimal("0.1")},
        {"inventory_accumulation_yoy": Decimal("-0.1")},
        {"inventory_drawdown_yoy": Decimal("0.1")},
        {"minimum_evidence_coverage": Decimal("1.1")},
        {"strong_demand_growth": Decimal("0"), "negative_demand_growth": Decimal("0")},
        {
            "inventory_accumulation_yoy": Decimal("0"),
            "inventory_drawdown_yoy": Decimal("0"),
        },
    ],
)
def test_supply_demand_config_rejects_invalid_thresholds(
    overrides: dict[str, Decimal],
) -> None:
    with pytest.raises(DomainValidationError):
        _config(**overrides)


def test_supply_demand_config_accepts_finite_explicit_calibration() -> None:
    assert _config().version == 1
