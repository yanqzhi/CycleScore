"""Pure PIT compatibility, calculation, and phase classification rules."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, localcontext

from cyclescope.domain.entities.industry_inventory import (
    IndustryInventoryClassification,
    IndustryInventorySnapshot,
    IndustryInventoryStatus,
)
from cyclescope.domain.entities.industry_signal import (
    IndustrySignalTemporalKind,
    IndustrySignalType,
)
from cyclescope.domain.entities.industry_signal_aggregate import (
    AggregateInputRole,
    AggregateScopeRole,
    AggregateStatus,
    IndustrySignalAggregateSnapshot,
)
from cyclescope.domain.entities.industry_supply_demand import (
    IndustrySupplyDemandConfig,
    IndustrySupplyDemandInputReference,
    IndustrySupplyDemandPhase,
    IndustrySupplyDemandSnapshot,
    IndustrySupplyDemandStatus,
)
from cyclescope.domain.exceptions import DomainValidationError

_QUANTUM = Decimal("0.000000000001")
_ZERO = Decimal(0)
_ONE = Decimal(1)


@dataclass(frozen=True, slots=True)
class _FlowPair:
    production: IndustrySignalAggregateSnapshot
    shipments: IndustrySignalAggregateSnapshot
    signature: tuple[object, ...]
    regions: tuple[tuple[int, str], ...]
    coverage: Decimal


def _year_ago(value: date) -> date | None:
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        return None


def _requested_regions(
    row: IndustrySignalAggregateSnapshot,
) -> tuple[tuple[int, str], ...]:
    return tuple(
        sorted(
            (scope.region_id, scope.region_code)
            for scope in row.requested_scopes
            if scope.role is AggregateScopeRole.CONSTITUENT
        )
    )


def _actual_regions(
    row: IndustrySignalAggregateSnapshot,
) -> tuple[tuple[int, str], ...]:
    ids_by_code = {
        scope.region_code: scope.region_id
        for scope in row.requested_scopes
        if scope.role is AggregateScopeRole.CONSTITUENT
    }
    codes = {
        item.region_code
        for item in row.contributors
        if item.included and item.role is AggregateInputRole.MEASURE
    }
    if not codes.issubset(ids_by_code):
        raise DomainValidationError(
            "Included contributor is outside the persisted requested scope."
        )
    return tuple(sorted((ids_by_code[code], code) for code in codes))


def _classification_signature(
    row: IndustrySignalAggregateSnapshot,
) -> tuple[tuple[int | None, int | None], ...]:
    return tuple(
        sorted(
            {
                (item.classification_version_id, item.classification_mapping_id)
                for item in row.contributors
                if item.included and item.role is AggregateInputRole.MEASURE
            },
            key=lambda item: (item[0] or 0, item[1] or 0),
        )
    )


def _cohort_signature(
    row: IndustrySignalAggregateSnapshot,
) -> tuple[object, ...]:
    return (
        row.industry_id,
        row.sub_industry_id,
        row.aggregate_region_id,
        row.aggregate_region_code,
        _requested_regions(row),
        row.source_id,
        row.unit_code,
        row.currency_code,
        _classification_signature(row),
        row.policy_code,
        row.policy_version,
        row.calculation_version,
    )


def _eligible_reason(
    row: IndustrySignalAggregateSnapshot,
    *,
    as_of: datetime,
    industry_id: int,
    sub_industry_id: int | None,
    aggregate_region_id: int | None,
    aggregate_region_code: str,
    requested_scope: tuple[tuple[int, str], ...],
    source_id: int | None,
) -> str | None:
    if row.id is None:
        return "Aggregate snapshot has no persisted ID."
    if row.industry_id != industry_id or row.sub_industry_id != sub_industry_id:
        return "Industry or sub-industry differs from the request."
    if row.aggregate_region_code != aggregate_region_code or (
        aggregate_region_id is not None
        and row.aggregate_region_id != aggregate_region_id
    ):
        return "Aggregate region differs from the request."
    if _requested_regions(row) != requested_scope:
        return "Requested constituent scope differs from the request."
    if not row.scope_complete:
        return "Aggregate scope is incomplete."
    if row.source_id is None:
        return "Aggregate has no explicit source."
    if source_id is not None and row.source_id != source_id:
        return "Aggregate source differs from the explicit source selection."
    if row.status is AggregateStatus.INSUFFICIENT_DATA:
        return "Aggregate status is INSUFFICIENT_DATA."
    if row.value is None:
        return "Aggregate value is unavailable."
    if row.temporal_kind is not IndustrySignalTemporalKind.PERIOD:
        return "Aggregate is not a period observation."
    if row.period_start is None or row.period_end is None:
        return "Aggregate period boundaries are missing."
    if row.as_of > as_of:
        return "Aggregate snapshot was calculated after the requested cutoff."
    if row.period_end > as_of.date():
        return "Aggregate period end is after the requested cutoff date."
    if any(
        contributor.included
        and (
            contributor.available_at > as_of
            or contributor.source_id != row.source_id
            or contributor.period_end is None
            or contributor.period_end > as_of.date()
        )
        for contributor in row.contributors
    ):
        return "Included contributor violates source or point-in-time policy."
    return None


def _reference_aggregate(
    row: IndustrySignalAggregateSnapshot,
    role: str,
    *,
    included: bool,
    reason: str | None = None,
) -> IndustrySupplyDemandInputReference:
    if row.id is None:
        raise DomainValidationError(
            "Persisted aggregate ID is required for provenance."
        )
    available = max(
        (item.available_at for item in row.contributors if item.included),
        default=row.as_of,
    )
    return IndustrySupplyDemandInputReference(
        role=role,
        aggregate_id=row.id,
        inventory_snapshot_id=None,
        period_start=row.period_start,
        period_end=row.period_end,
        source_id=row.source_id,
        unit_code=row.unit_code.value,
        currency_code=row.currency_code,
        available_at=available,
        contributing_regions=_actual_regions(row),
        coverage=row.coverage_ratio,
        policy_code=row.policy_code.value,
        policy_version=row.policy_version,
        calculation_version=row.calculation_version,
        classification_references=_classification_signature(row),
        contributor_revisions=tuple(
            sorted(
                (item.observation_id, item.source_id, item.revision_number)
                for item in row.contributors
                if item.included and item.role is AggregateInputRole.MEASURE
            )
        ),
        included=included,
        exclusion_reason=reason,
    )


def _reference_inventory(
    row: IndustryInventorySnapshot,
    *,
    included: bool,
    reason: str | None = None,
) -> IndustrySupplyDemandInputReference:
    if row.id is None:
        raise DomainValidationError(
            "Persisted inventory ID is required for provenance."
        )
    return IndustrySupplyDemandInputReference(
        role="INVENTORY_CONTEXT",
        aggregate_id=None,
        inventory_snapshot_id=row.id,
        period_start=None,
        period_end=row.observation_date,
        source_id=row.source_id,
        unit_code=row.unit_code,
        currency_code=row.currency_code,
        available_at=row.as_of,
        contributing_regions=row.contributing_regions,
        coverage=row.coverage,
        included=included,
        exclusion_reason=reason,
    )


def _latest(
    rows: list[IndustrySignalAggregateSnapshot],
) -> IndustrySignalAggregateSnapshot | None:
    return max(rows, key=lambda row: (row.as_of, row.id or 0), default=None)


def _pair_rows(
    aggregates: tuple[IndustrySignalAggregateSnapshot, ...],
    *,
    as_of: datetime,
    industry_id: int,
    sub_industry_id: int | None,
    aggregate_region_id: int | None,
    aggregate_region_code: str,
    requested_scope: tuple[tuple[int, str], ...],
    source_id: int | None,
) -> tuple[list[_FlowPair], dict[int, str]]:
    accepted: list[IndustrySignalAggregateSnapshot] = []
    rejection: dict[int, str] = {}
    for row in aggregates:
        if row.signal_type not in {
            IndustrySignalType.PRODUCTION,
            IndustrySignalType.SHIPMENTS,
        }:
            continue
        reason = _eligible_reason(
            row,
            as_of=as_of,
            industry_id=industry_id,
            sub_industry_id=sub_industry_id,
            aggregate_region_id=aggregate_region_id,
            aggregate_region_code=aggregate_region_code,
            requested_scope=requested_scope,
            source_id=source_id,
        )
        if reason is not None:
            if (
                row.id is not None
                and row.as_of <= as_of
                and (row.period_end is None or row.period_end <= as_of.date())
            ):
                rejection[row.id] = reason
            continue
        accepted.append(row)

    groups: dict[
        tuple[tuple[object, ...], date, date],
        dict[IndustrySignalType, list[IndustrySignalAggregateSnapshot]],
    ] = {}
    for row in accepted:
        assert row.period_start is not None and row.period_end is not None
        key = (_cohort_signature(row), row.period_start, row.period_end)
        groups.setdefault(key, {}).setdefault(row.signal_type, []).append(row)

    pairs: list[_FlowPair] = []
    for (signature, _start, _end), rows_by_type in groups.items():
        production = _latest(rows_by_type.get(IndustrySignalType.PRODUCTION, []))
        shipments = _latest(rows_by_type.get(IndustrySignalType.SHIPMENTS, []))
        if production is None or shipments is None:
            continue
        production_regions = _actual_regions(production)
        shipment_regions = _actual_regions(shipments)
        if production_regions != shipment_regions:
            rejection[production.id or 0] = (
                "Actual production and shipments contributor regions differ."
            )
            rejection[shipments.id or 0] = (
                "Actual production and shipments contributor regions differ."
            )
            continue
        if (
            production.coverage_ratio is None
            or shipments.coverage_ratio is None
            or production.coverage_ratio != shipments.coverage_ratio
        ):
            rejection[production.id or 0] = (
                "Production and shipments coverage is missing or differs."
            )
            rejection[shipments.id or 0] = (
                "Production and shipments coverage is missing or differs."
            )
            continue
        pairs.append(
            _FlowPair(
                production,
                shipments,
                signature,
                production_regions,
                production.coverage_ratio,
            )
        )
        for row in rows_by_type[IndustrySignalType.PRODUCTION]:
            if row.id != production.id:
                rejection[row.id or 0] = "Superseded by a later eligible aggregate."
        for row in rows_by_type[IndustrySignalType.SHIPMENTS]:
            if row.id != shipments.id:
                rejection[row.id or 0] = "Superseded by a later eligible aggregate."
    return pairs, rejection


def _matching_inventory_reason(
    row: IndustryInventorySnapshot,
    pair: _FlowPair,
    *,
    as_of: datetime,
    industry_id: int,
    sub_industry_id: int | None,
    requested_scope: tuple[tuple[int, str], ...],
) -> str | None:
    if row.id is None:
        return "Inventory snapshot has no persisted ID."
    if row.as_of > as_of:
        return "Inventory snapshot was calculated after the requested cutoff."
    if row.status is IndustryInventoryStatus.INSUFFICIENT_DATA:
        return "Inventory snapshot status is INSUFFICIENT_DATA."
    production = pair.production
    if row.industry_id != industry_id or row.sub_industry_id != sub_industry_id:
        return "Inventory industry or sub-industry differs from the flow cohort."
    if (
        row.observation_date != production.period_end
        or row.aggregate_region_code != production.aggregate_region_code
        or row.source_id != production.source_id
        or row.unit_code != production.unit_code.value
        or row.currency_code != production.currency_code
    ):
        return "Inventory date, region, source, unit, or currency differs from flow."
    if row.requested_scope != requested_scope:
        return "Inventory requested scope differs from the flow cohort."
    if row.contributing_regions != pair.regions:
        return "Inventory actual contributor regions differ from the flow pair."
    if row.coverage is None or row.coverage != pair.coverage:
        return "Inventory coverage is missing or differs from the flow pair."
    if any(reference.available_at > as_of for reference in row.input_references):
        return "Inventory input reference violates point-in-time availability."
    production_refs = [
        item
        for item in row.input_references
        if item.role == "PRODUCTION" and item.included
    ]
    shipment_refs = [
        item
        for item in row.input_references
        if item.role == "SHIPMENTS" and item.included
    ]
    if not any(
        item.aggregate_id == production.id for item in production_refs
    ) or not any(item.aggregate_id == pair.shipments.id for item in shipment_refs):
        return "Inventory does not reference the exact selected flow aggregate IDs."
    return None


def _checked(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise DomainValidationError("Supply-demand result must be finite.")
    try:
        with localcontext() as context:
            context.prec = 80
            rounded = value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)
    except DecimalException as exc:
        raise DomainValidationError(
            "Supply-demand result exceeds NUMERIC(38, 12) precision."
        ) from exc
    parts = rounded.as_tuple()
    if (
        not isinstance(parts.exponent, int)
        or max(len(parts.digits) + parts.exponent, 0) > 26
    ):
        raise DomainValidationError("Supply-demand result exceeds NUMERIC(38, 12).")
    return rounded


def _evidence_fraction(count: int) -> Decimal:
    try:
        with localcontext() as context:
            context.prec = 80
            return (Decimal(count) / Decimal(3)).quantize(
                Decimal("0.0000001"), rounding=ROUND_HALF_EVEN
            )
    except DecimalException as exc:
        raise DomainValidationError("Evidence coverage arithmetic failed.") from exc


def _difference_raw(left: Decimal, right: Decimal) -> Decimal:
    try:
        with localcontext() as context:
            context.prec = 80
            return left - right
    except DecimalException as exc:
        raise DomainValidationError("Supply-demand arithmetic failed.") from exc


def _ratio(numerator: Decimal, denominator: Decimal, label: str) -> Decimal:
    if denominator <= 0:
        raise DomainValidationError(f"{label} denominator must be positive.")
    try:
        with localcontext() as context:
            context.prec = 80
            return numerator / denominator
    except DecimalException as exc:
        raise DomainValidationError(f"{label} arithmetic failed.") from exc


def _ratio_change(numerator: Decimal, denominator: Decimal, label: str) -> Decimal:
    if denominator <= 0:
        raise DomainValidationError(f"{label} denominator must be positive.")
    try:
        with localcontext() as context:
            context.prec = 80
            return (numerator / denominator) - _ONE
    except DecimalException as exc:
        raise DomainValidationError(f"{label} arithmetic failed.") from exc


def _phase(
    *,
    gap_ratio: Decimal | None,
    shipment_growth: Decimal | None,
    inventory_yoy: Decimal | None,
    inventory_classification: IndustryInventoryClassification | None,
    evidence_coverage: Decimal,
    config: IndustrySupplyDemandConfig,
) -> IndustrySupplyDemandPhase:
    unknown = IndustrySupplyDemandPhase.UNKNOWN
    if evidence_coverage < config.minimum_evidence_coverage or gap_ratio is None:
        return unknown

    inventory_accumulation = (
        inventory_yoy is not None and inventory_yoy >= config.inventory_accumulation_yoy
    )
    inventory_drawdown = (
        inventory_classification is IndustryInventoryClassification.DRAWDOWN
        or (
            inventory_yoy is not None and inventory_yoy <= config.inventory_drawdown_yoy
        )
    )
    oversupply = gap_ratio > config.flow_gap_tolerance and (
        (shipment_growth is not None and shipment_growth < _ZERO)
        or inventory_accumulation
    )
    if oversupply:
        return IndustrySupplyDemandPhase.OVERSUPPLY
    undersupply = gap_ratio < -config.flow_gap_tolerance and (
        (shipment_growth is not None and shipment_growth >= config.strong_demand_growth)
        or inventory_drawdown
    )
    if undersupply:
        return IndustrySupplyDemandPhase.UNDERSUPPLY

    within_gap = -config.flow_gap_tolerance <= gap_ratio <= config.flow_gap_tolerance
    if (
        within_gap
        and shipment_growth is not None
        and shipment_growth >= config.strong_demand_growth
        and inventory_drawdown
    ):
        return IndustrySupplyDemandPhase.DEMAND_RECOVERY
    if shipment_growth is not None and shipment_growth <= config.negative_demand_growth:
        return IndustrySupplyDemandPhase.DEMAND_SLOWDOWN

    inventory_not_drawdown = (
        inventory_yoy is not None
        and inventory_yoy > config.inventory_drawdown_yoy
        and inventory_classification is not IndustryInventoryClassification.DRAWDOWN
    )
    if (
        within_gap
        and shipment_growth is not None
        and shipment_growth >= config.strong_demand_growth
        and inventory_not_drawdown
    ):
        return IndustrySupplyDemandPhase.EXPANSION
    inventory_not_contradictory = (
        inventory_not_drawdown
        and inventory_yoy is not None
        and inventory_yoy < config.inventory_accumulation_yoy
    )
    if (
        within_gap
        and shipment_growth is not None
        and config.negative_demand_growth < shipment_growth
        and shipment_growth < config.strong_demand_growth
        and inventory_not_contradictory
    ):
        return IndustrySupplyDemandPhase.BALANCED
    return unknown


def calculate_industry_supply_demand(
    *,
    aggregates: tuple[IndustrySignalAggregateSnapshot, ...],
    inventories: tuple[IndustryInventorySnapshot, ...],
    industry_id: int,
    sub_industry_id: int | None,
    aggregate_region_id: int | None,
    aggregate_region_code: str,
    requested_scope: tuple[tuple[int, str], ...],
    target_period_end: date,
    as_of: datetime,
    calculated_at: datetime,
    config: IndustrySupplyDemandConfig,
    source_id: int | None = None,
) -> IndustrySupplyDemandSnapshot:
    """Calculate only from persisted, exact-period, PIT-compatible snapshots."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise DomainValidationError("as_of must be timezone-aware.")
    if calculated_at.tzinfo is None or calculated_at.utcoffset() is None:
        raise DomainValidationError("calculated_at must be timezone-aware.")
    cutoff = as_of.astimezone(UTC)
    calculated_at = calculated_at.astimezone(UTC)
    scope = tuple(sorted(requested_scope))
    if not scope or len(set(scope)) != len(scope):
        raise DomainValidationError("Requested scope must be unique and non-empty.")
    if not isinstance(target_period_end, date) or isinstance(
        target_period_end, datetime
    ):
        raise DomainValidationError("target_period_end must be a calendar date.")

    pairs, rejected = _pair_rows(
        aggregates,
        as_of=cutoff,
        industry_id=industry_id,
        sub_industry_id=sub_industry_id,
        aggregate_region_id=aggregate_region_id,
        aggregate_region_code=aggregate_region_code,
        requested_scope=scope,
        source_id=source_id,
    )
    target_pairs = [
        pair for pair in pairs if pair.production.period_end == target_period_end
    ]
    source_ids = {pair.production.source_id for pair in target_pairs}
    if source_id is None and len(source_ids) > 1:
        raise DomainValidationError(
            "Multiple eligible source cohorts require explicit source selection."
        )
    current = max(
        target_pairs,
        key=lambda pair: (
            pair.production.period_end or date.min,
            pair.production.as_of,
            pair.production.id or 0,
            pair.shipments.as_of,
            pair.shipments.id or 0,
        ),
        default=None,
    )

    prior: _FlowPair | None = None
    if current is not None:
        assert current.production.period_start is not None
        assert current.production.period_end is not None
        prior_start = _year_ago(current.production.period_start)
        prior_end = _year_ago(current.production.period_end)
        if prior_start is not None and prior_end is not None:
            current_duration = (
                current.production.period_end - current.production.period_start
            )
            prior = next(
                (
                    pair
                    for pair in sorted(
                        pairs,
                        key=lambda item: (
                            item.production.as_of,
                            item.production.id or 0,
                        ),
                        reverse=True,
                    )
                    if pair.signature == current.signature
                    and pair.production.period_start == prior_start
                    and pair.production.period_end == prior_end
                    and pair.production.period_end - pair.production.period_start
                    == current_duration
                    and pair.regions == current.regions
                    and pair.coverage == current.coverage
                ),
                None,
            )

    inventory_matches: list[IndustryInventorySnapshot] = []
    inventory_rejections: dict[int, str] = {}
    if current is not None:
        for candidate_inventory in inventories:
            reason = _matching_inventory_reason(
                candidate_inventory,
                current,
                as_of=cutoff,
                industry_id=industry_id,
                sub_industry_id=sub_industry_id,
                requested_scope=scope,
            )
            if reason is None:
                inventory_matches.append(candidate_inventory)
            elif (
                candidate_inventory.id is not None
                and candidate_inventory.as_of <= cutoff
            ):
                inventory_rejections[candidate_inventory.id] = reason
    inventory = max(
        inventory_matches,
        key=lambda row: (row.as_of, row.id or 0),
        default=None,
    )
    for row in inventory_matches:
        if row.id != (inventory.id if inventory is not None else None):
            inventory_rejections[row.id or 0] = (
                "Superseded by a later compatible inventory snapshot."
            )

    reasons: list[str] = []
    if current is None:
        reasons.append(
            "No valid compatible production/shipments pair is available for "
            f"target period end {target_period_end.isoformat()}."
        )
    else:
        if prior is None:
            reasons.append(
                "No exact prior-year production/shipments anniversary pair "
                "is available."
            )
        if inventory is None:
            reasons.append("No compatible Sprint 18 inventory context is available.")

    production = current.production if current is not None else None
    shipments = current.shipments if current is not None else None
    flow_gap_raw = None
    gap_ratio = None
    shipment_growth = None
    if production is not None and shipments is not None:
        assert production.value is not None and shipments.value is not None
        flow_gap_raw = _difference_raw(production.value, shipments.value)
        if shipments.value > _ZERO:
            gap_ratio = _ratio(
                flow_gap_raw,
                shipments.value,
                "Flow gap ratio",
            )
        else:
            reasons.append(
                "Flow gap ratio is unavailable because current shipments are "
                "not positive."
            )
    if prior is not None and shipments is not None:
        assert shipments.value is not None and prior.shipments.value is not None
        if prior.shipments.value > _ZERO:
            shipment_growth = _ratio_change(
                shipments.value, prior.shipments.value, "Shipment YoY"
            )
        else:
            reasons.append(
                "Shipment YoY is unavailable because prior-year shipments "
                "are not positive."
            )

    current_pair_available = current is not None
    prior_pair_available = prior is not None and shipment_growth is not None
    inventory_available = inventory is not None
    evidence_count = sum(
        (current_pair_available, prior_pair_available, inventory_available)
    )
    evidence_coverage = _evidence_fraction(evidence_count)
    coverage = current.coverage if current is not None else None
    if current is None or coverage is None or coverage < config.minimum_coverage:
        status = IndustrySupplyDemandStatus.INSUFFICIENT_DATA
        if current is not None and coverage is None:
            reasons.append("Current flow-pair coverage is unknown.")
        elif (
            current is not None
            and coverage is not None
            and coverage < config.minimum_coverage
        ):
            reasons.append(
                "Current flow-pair coverage is below the configured minimum."
            )
    elif (
        evidence_coverage == Decimal(1)
        and coverage == Decimal(1)
        and gap_ratio is not None
        and shipment_growth is not None
    ):
        status = IndustrySupplyDemandStatus.AVAILABLE
    else:
        status = IndustrySupplyDemandStatus.PARTIAL

    inventory_classification = inventory.classification if inventory else None
    inventory_trend = inventory.trend if inventory else None
    inventory_yoy = inventory.yoy_growth if inventory else None
    inventory_acceleration = inventory.growth_acceleration if inventory else None
    phase = (
        _phase(
            gap_ratio=gap_ratio,
            shipment_growth=shipment_growth,
            inventory_yoy=inventory_yoy,
            inventory_classification=inventory_classification,
            evidence_coverage=evidence_coverage,
            config=config,
        )
        if status is not IndustrySupplyDemandStatus.INSUFFICIENT_DATA
        else IndustrySupplyDemandPhase.UNKNOWN
    )
    if (
        evidence_coverage < config.minimum_evidence_coverage
        and status is not IndustrySupplyDemandStatus.INSUFFICIENT_DATA
    ):
        reasons.append("Evidence coverage is below the configured minimum.")

    refs: list[IndustrySupplyDemandInputReference] = []
    if current is not None:
        refs.extend(
            (
                _reference_aggregate(
                    current.production, "CURRENT_PRODUCTION", included=True
                ),
                _reference_aggregate(
                    current.shipments, "CURRENT_SHIPMENTS", included=True
                ),
            )
        )
    if prior is not None:
        refs.extend(
            (
                _reference_aggregate(
                    prior.production, "PRIOR_YEAR_PRODUCTION", included=True
                ),
                _reference_aggregate(
                    prior.shipments, "PRIOR_YEAR_SHIPMENTS", included=True
                ),
            )
        )
    if inventory is not None:
        refs.append(_reference_inventory(inventory, included=True))
    selected_aggregate_ids = {ref.aggregate_id for ref in refs if ref.aggregate_id}
    selected_inventory_ids = {
        ref.inventory_snapshot_id for ref in refs if ref.inventory_snapshot_id
    }
    for candidate_flow in aggregates:
        if (
            candidate_flow.id is None
            or candidate_flow.id in selected_aggregate_ids
            or candidate_flow.signal_type
            not in {IndustrySignalType.PRODUCTION, IndustrySignalType.SHIPMENTS}
            or candidate_flow.as_of > cutoff
            or (
                candidate_flow.period_end is not None
                and candidate_flow.period_end > cutoff.date()
            )
        ):
            continue
        role = (
            "EXCLUDED_PRODUCTION"
            if candidate_flow.signal_type is IndustrySignalType.PRODUCTION
            else "EXCLUDED_SHIPMENTS"
        )
        refs.append(
            _reference_aggregate(
                candidate_flow,
                role,
                included=False,
                reason=rejected.get(
                    candidate_flow.id,
                    "No exact compatible selected-period pair uses this aggregate.",
                ),
            )
        )
    for candidate_inventory in inventories:
        if (
            candidate_inventory.id is None
            or candidate_inventory.id in selected_inventory_ids
            or candidate_inventory.as_of > cutoff
        ):
            continue
        refs.append(
            _reference_inventory(
                candidate_inventory,
                included=False,
                reason=inventory_rejections.get(
                    candidate_inventory.id,
                    "Inventory snapshot is not the exact compatible context.",
                ),
            )
        )

    unique_refs = {
        (ref.aggregate_id, ref.inventory_snapshot_id, ref.role): ref for ref in refs
    }
    refs = sorted(
        unique_refs.values(),
        key=lambda ref: (
            ref.role,
            ref.period_end or date.min,
            ref.aggregate_id or ref.inventory_snapshot_id or 0,
        ),
    )
    return IndustrySupplyDemandSnapshot(
        industry_id=industry_id,
        sub_industry_id=sub_industry_id,
        aggregate_region_id=(
            current.production.aggregate_region_id
            if current is not None
            else aggregate_region_id
        ),
        aggregate_region_code=aggregate_region_code,
        requested_scope=scope,
        contributing_regions=current.regions if current is not None else (),
        source_id=current.production.source_id if current is not None else source_id,
        unit_code=(current.production.unit_code.value if current is not None else None),
        currency_code=(
            current.production.currency_code if current is not None else None
        ),
        period_start=(production.period_start if production is not None else None),
        period_end=(production.period_end if production is not None else None),
        observation_date=(production.period_end if production is not None else None),
        as_of=cutoff,
        calculated_at=calculated_at,
        phase=phase,
        status=status,
        production_value=production.value if production is not None else None,
        shipments_value=shipments.value if shipments is not None else None,
        flow_gap=_checked(flow_gap_raw) if flow_gap_raw is not None else None,
        flow_gap_ratio=_checked(gap_ratio) if gap_ratio is not None else None,
        shipment_growth_yoy=(
            _checked(shipment_growth) if shipment_growth is not None else None
        ),
        inventory_snapshot_id=inventory.id if inventory is not None else None,
        inventory_classification=inventory_classification,
        inventory_trend=inventory_trend,
        inventory_yoy_growth=inventory_yoy,
        inventory_growth_acceleration=inventory_acceleration,
        inventory_coverage=inventory.coverage if inventory is not None else None,
        inventory_confidence=inventory.confidence if inventory is not None else None,
        coverage=coverage,
        evidence_coverage=evidence_coverage,
        confidence=None,
        config=config,
        input_references=tuple(refs),
        unavailable_reasons=tuple(dict.fromkeys(reasons)),
    )
