"""Versioned and provider-independent industry signal aggregation rules."""

from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, localcontext

from cyclescope.domain.entities.industry_signal import (
    IndustrySignalObservation,
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
    IndustrySignalAggregationPolicy,
)
from cyclescope.domain.entities.region import (
    Region,
    RegionRelationship,
    RegionRelationshipType,
    RegionType,
)
from cyclescope.domain.exceptions import DomainValidationError

CALCULATION_VERSION = 1
_RESULT_QUANTUM = Decimal("0.000000000001")
_MAX_INTEGER_DIGITS = 26
_MAX_AGGREGATION_CONTRIBUTORS = 100_000
_SUM_CONTEXT_PRECISION = 43  # 38 input digits + 5 carry digits at the size limit.
_FLOW_TYPES = frozenset(
    {
        IndustrySignalType.PRODUCTION,
        IndustrySignalType.SHIPMENTS,
        IndustrySignalType.SALES,
        IndustrySignalType.ORDERS,
    }
)


def resolve_aggregation_policy(
    policy_code: str,
    policy_version: int,
    signal_type: IndustrySignalType,
    minimum_coverage: Decimal | None = None,
) -> IndustrySignalAggregationPolicy:
    """Resolve one explicitly selected supported policy and validate its signal."""
    try:
        code = AggregationPolicyCode(policy_code)
    except ValueError as exc:
        raise DomainValidationError("Unknown aggregation policy code.") from exc
    if policy_version != 1:
        raise DomainValidationError("Only aggregation policy version 1 is supported.")
    allowed: dict[AggregationPolicyCode, tuple[object, ...]] = {
        AggregationPolicyCode.FLOW_SUM: tuple(_FLOW_TYPES),
        AggregationPolicyCode.INVENTORY_SUM: (IndustrySignalType.INVENTORY,),
        AggregationPolicyCode.CAPACITY_SUM: (IndustrySignalType.CAPACITY,),
        AggregationPolicyCode.CAPACITY_WEIGHTED_UTILIZATION: (
            IndustrySignalType.CAPACITY_UTILIZATION,
        ),
    }
    if signal_type not in allowed[code]:
        raise DomainValidationError(
            f"Policy {code.value} does not support {signal_type.value}."
        )
    operation = (
        AggregationOperation.CAPACITY_WEIGHTED_AVERAGE
        if code is AggregationPolicyCode.CAPACITY_WEIGHTED_UTILIZATION
        else AggregationOperation.SUM
    )
    return IndustrySignalAggregationPolicy(
        policy_code=code,
        version=policy_version,
        operation=operation,
        signal_type=signal_type,
        minimum_coverage=(
            minimum_coverage if minimum_coverage is not None else Decimal("0.80")
        ),
    )


def validate_aggregation_region_scope(
    aggregate_scope: Region,
    constituents: tuple[Region, ...],
    relationships: tuple[RegionRelationship, ...],
) -> None:
    """Validate explicit membership and provable non-overlap without expansion."""
    if not constituents:
        raise DomainValidationError("At least one constituent region is required.")
    if len(constituents) > _MAX_AGGREGATION_CONTRIBUTORS:
        raise DomainValidationError(
            "Requested aggregation scope exceeds 100,000 regions."
        )
    codes = [region.region_code for region in constituents]
    if len(codes) != len(set(codes)):
        raise DomainValidationError("Duplicate constituent region codes are invalid.")
    if len(constituents) > 1 and any(
        region.region_type is not RegionType.COUNTRY for region in constituents
    ):
        raise DomainValidationError(
            "Non-overlap cannot be established for multiple non-country scopes."
        )
    for constituent in constituents:
        if constituent.id == aggregate_scope.id:
            if len(constituents) > 1:
                raise DomainValidationError(
                    "Aggregate scope cannot also be one of multiple constituents."
                )
            continue
        if aggregate_scope.region_type in {RegionType.GLOBAL, RegionType.CONTINENT}:
            if constituent.region_type is not RegionType.COUNTRY or not _contained_in(
                constituent.id or 0,
                aggregate_scope.id or 0,
                relationships,
            ):
                raise DomainValidationError(
                    "Country constituent is not explicitly contained in "
                    "the aggregate scope."
                )
        elif aggregate_scope.region_type in {
            RegionType.ECONOMIC_REGION,
            RegionType.MARKET_REGION,
        }:
            if constituent.region_type is not RegionType.COUNTRY or not any(
                edge.parent_region_id == aggregate_scope.id
                and edge.child_region_id == constituent.id
                and edge.relationship_type is RegionRelationshipType.MEMBER_OF
                for edge in relationships
            ):
                raise DomainValidationError(
                    "Country constituent is not explicitly a member of "
                    "the aggregate scope."
                )
        elif aggregate_scope.region_type is RegionType.COUNTRY:
            raise DomainValidationError(
                "A country scope cannot contain a different constituent scope."
            )
        else:
            raise DomainValidationError(
                "Containment cannot be established for this aggregate scope type."
            )


def _contained_in(
    region_id: int,
    ancestor_id: int,
    relationships: tuple[RegionRelationship, ...],
) -> bool:
    children: dict[int, set[int]] = {}
    for edge in relationships:
        if edge.relationship_type is RegionRelationshipType.CONTAINS:
            children.setdefault(edge.parent_region_id, set()).add(edge.child_region_id)
    pending = list(children.get(ancestor_id, set()))
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        if current == region_id:
            return True
        if current not in visited:
            visited.add(current)
            pending.extend(children.get(current, set()))
    return False


def calculate_industry_signal_aggregate(
    *,
    policy: IndustrySignalAggregationPolicy,
    observations: tuple[IndustrySignalObservation, ...],
    capacity_observations: tuple[IndustrySignalObservation, ...] = (),
    industry_id: int,
    sub_industry_id: int | None,
    aggregate_region_code: str,
    constituent_region_codes: tuple[str, ...],
    unit_code: IndustrySignalUnit,
    currency_code: str | None,
    observation_date: date | None,
    period_start: date | None,
    period_end: date | None,
    as_of: datetime,
    calculated_at: datetime,
    expected_contributor_count: int | None,
    requested_source_id: int | None = None,
    aggregate_region_id: int,
    constituent_regions: tuple[Region, ...],
) -> IndustrySignalAggregateSnapshot:
    """Calculate one aggregate from already PIT-selected Domain observations."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise DomainValidationError("as_of must be timezone-aware.")
    as_of = as_of.astimezone(UTC)
    if not constituent_region_codes or len(set(constituent_region_codes)) != len(
        constituent_region_codes
    ):
        raise DomainValidationError(
            "Constituent region codes must be unique and non-empty."
        )
    if expected_contributor_count is not None and (
        expected_contributor_count < len(constituent_region_codes)
    ):
        raise DomainValidationError(
            "Expected contributor count cannot be less than selected constituents."
        )
    if expected_contributor_count is not None and (
        expected_contributor_count > _MAX_AGGREGATION_CONTRIBUTORS
    ):
        raise DomainValidationError(
            "Expected contributor count exceeds the 100,000-region limit."
        )
    if len(constituent_region_codes) > _MAX_AGGREGATION_CONTRIBUTORS:
        raise DomainValidationError(
            "Requested aggregation scope exceeds 100,000 regions."
        )
    if aggregate_region_id < 1:
        raise DomainValidationError("aggregate_region_id must be positive.")
    if (
        tuple(region.region_code for region in constituent_regions)
        != constituent_region_codes
    ):
        raise DomainValidationError(
            "Constituent region identities do not match request codes."
        )
    if any(region.id is None or region.id < 1 for region in constituent_regions):
        raise DomainValidationError("Constituent regions require persisted identities.")
    allowed_units = {
        IndustrySignalType.INVENTORY: {
            IndustrySignalUnit.TONNE,
            IndustrySignalUnit.THOUSAND_TONNE,
            IndustrySignalUnit.UNIT,
            IndustrySignalUnit.THOUSAND_UNITS,
            IndustrySignalUnit.CURRENCY,
            IndustrySignalUnit.INDEX,
        },
        IndustrySignalType.PRODUCTION: {
            IndustrySignalUnit.TONNE,
            IndustrySignalUnit.THOUSAND_TONNE,
            IndustrySignalUnit.UNIT,
            IndustrySignalUnit.THOUSAND_UNITS,
        },
        IndustrySignalType.SHIPMENTS: {
            IndustrySignalUnit.TONNE,
            IndustrySignalUnit.THOUSAND_TONNE,
            IndustrySignalUnit.UNIT,
            IndustrySignalUnit.THOUSAND_UNITS,
        },
        IndustrySignalType.SALES: {
            IndustrySignalUnit.TONNE,
            IndustrySignalUnit.THOUSAND_TONNE,
            IndustrySignalUnit.UNIT,
            IndustrySignalUnit.THOUSAND_UNITS,
            IndustrySignalUnit.CURRENCY,
            IndustrySignalUnit.INDEX,
        },
        IndustrySignalType.ORDERS: {
            IndustrySignalUnit.TONNE,
            IndustrySignalUnit.THOUSAND_TONNE,
            IndustrySignalUnit.UNIT,
            IndustrySignalUnit.THOUSAND_UNITS,
            IndustrySignalUnit.CURRENCY,
            IndustrySignalUnit.INDEX,
        },
        IndustrySignalType.CAPACITY: {
            IndustrySignalUnit.TONNE,
            IndustrySignalUnit.THOUSAND_TONNE,
            IndustrySignalUnit.UNIT,
            IndustrySignalUnit.THOUSAND_UNITS,
        },
        IndustrySignalType.CAPACITY_UTILIZATION: {IndustrySignalUnit.PERCENTAGE},
    }
    if unit_code not in allowed_units[policy.signal_type]:
        raise DomainValidationError("Unit is incompatible with aggregation signal.")
    if unit_code is IndustrySignalUnit.INDEX:
        raise DomainValidationError("INDEX observations are not additive in v1.")
    if unit_code is IndustrySignalUnit.CURRENCY:
        if (
            currency_code is None
            or len(currency_code) != 3
            or not currency_code.isascii()
            or not currency_code.isalpha()
            or not currency_code.isupper()
        ):
            raise DomainValidationError(
                "currency_code must be three uppercase letters."
            )
    elif currency_code is not None:
        raise DomainValidationError("currency_code is only valid for CURRENCY unit.")
    if policy.signal_type is IndustrySignalType.CAPACITY_UTILIZATION:
        if unit_code is not IndustrySignalUnit.PERCENTAGE or currency_code is not None:
            raise DomainValidationError(
                "Capacity-weighted utilization output must be PERCENTAGE."
            )
        if any(
            observation.unit_code is not IndustrySignalUnit.PERCENTAGE
            for observation in observations
        ):
            raise DomainValidationError("Utilization inputs must use PERCENTAGE.")
    selected = _validate_observations(
        policy,
        observations,
        industry_id,
        sub_industry_id,
        observation_date,
        period_start,
        period_end,
        as_of,
        unit_code,
        currency_code,
    )
    if requested_source_id is not None and any(
        row.source_id != requested_source_id for row in selected
    ):
        raise DomainValidationError("Observation does not match requested source.")
    capacities = _validate_capacity_observations(
        capacity_observations,
        industry_id,
        sub_industry_id,
        observation_date,
        as_of,
        selected,
    )
    expected_regions = set(constituent_region_codes)
    if any(row.region_code not in expected_regions for row in selected):
        raise DomainValidationError("An observation is outside the selected regions.")
    if any(row.region_code not in expected_regions for row in capacities):
        raise DomainValidationError(
            "A capacity observation is outside the selected regions."
        )
    if policy.operation is AggregationOperation.CAPACITY_WEIGHTED_AVERAGE:
        value, contributors, missing, actual_count, source_id = _weighted_value(
            selected, capacities, constituent_region_codes
        )
        source_id = source_id or requested_source_id
        output_unit = IndustrySignalUnit.PERCENTAGE
        currency_code = None
        temporal_kind = IndustrySignalTemporalKind.POINT
    else:
        value, contributors, missing, actual_count, source_id = _sum_value(
            selected, constituent_region_codes
        )
        source_id = source_id or requested_source_id
        output_unit = unit_code
        temporal_kind = (
            IndustrySignalTemporalKind.PERIOD
            if policy.signal_type
            in {
                IndustrySignalType.PRODUCTION,
                IndustrySignalType.SHIPMENTS,
                IndustrySignalType.SALES,
                IndustrySignalType.ORDERS,
            }
            else IndustrySignalTemporalKind.POINT
        )
    coverage = (
        (Decimal(actual_count) / Decimal(expected_contributor_count)).quantize(
            Decimal("0.0000001"), rounding=ROUND_HALF_EVEN
        )
        if expected_contributor_count is not None
        else None
    )
    if expected_contributor_count is not None and expected_contributor_count > len(
        constituent_region_codes
    ):
        missing = (
            *missing,
            "Expected contributor count includes unselected regions; "
            "anonymous contributors cannot be audited.",
        )
    if actual_count == 0 or (
        coverage is not None and coverage < policy.minimum_coverage
    ):
        status = AggregateStatus.INSUFFICIENT_DATA
        value = None
    elif coverage is None:
        status = AggregateStatus.PARTIAL
        missing = (
            *missing,
            "Expected contributor universe was not supplied; coverage is unknown.",
        )
    elif coverage < 1:
        status = AggregateStatus.PARTIAL
    else:
        status = AggregateStatus.AVAILABLE
    if policy.signal_type in {
        IndustrySignalType.PRODUCTION,
        IndustrySignalType.SHIPMENTS,
        IndustrySignalType.SALES,
        IndustrySignalType.ORDERS,
    }:
        temporal_kind = IndustrySignalTemporalKind.PERIOD
    return IndustrySignalAggregateSnapshot(
        industry_id=industry_id,
        sub_industry_id=sub_industry_id,
        signal_type=policy.signal_type,
        temporal_kind=temporal_kind,
        aggregate_region_code=aggregate_region_code,
        source_id=source_id,
        unit_code=output_unit,
        currency_code=currency_code,
        observation_date=observation_date,
        period_start=period_start,
        period_end=period_end,
        as_of=as_of,
        calculated_at=calculated_at,
        policy_code=policy.policy_code,
        policy_version=policy.version,
        calculation_version=CALCULATION_VERSION,
        operation=policy.operation,
        minimum_coverage=policy.minimum_coverage,
        value=value,
        status=status,
        expected_contributor_count=expected_contributor_count,
        actual_contributor_count=actual_count,
        coverage_ratio=coverage,
        confidence=None,
        missing_reasons=tuple(dict.fromkeys(missing)),
        validation_warnings=(),
        contributors=contributors,
        aggregate_region_id=aggregate_region_id,
        requested_scopes=tuple(
            sorted(
                (
                    IndustrySignalAggregateScope(
                        aggregate_region_id,
                        aggregate_region_code,
                        AggregateScopeRole.AGGREGATE,
                    ),
                    *(
                        IndustrySignalAggregateScope(
                            region.id or 0,
                            region.region_code,
                            AggregateScopeRole.CONSTITUENT,
                        )
                        for region in constituent_regions
                    ),
                ),
                key=lambda scope: (
                    scope.role.value,
                    scope.region_code,
                    scope.region_id,
                ),
            )
        ),
        scope_complete=True,
    )


def _validate_observations(
    policy: IndustrySignalAggregationPolicy,
    observations: tuple[IndustrySignalObservation, ...],
    industry_id: int,
    sub_industry_id: int | None,
    observation_date: date | None,
    period_start: date | None,
    period_end: date | None,
    as_of: datetime,
    requested_unit: IndustrySignalUnit,
    requested_currency: str | None,
) -> tuple[IndustrySignalObservation, ...]:
    if policy.signal_type in _FLOW_TYPES:
        if observation_date is not None or period_start is None or period_end is None:
            raise DomainValidationError(
                "Period flow aggregation requires exact boundaries."
            )
    elif observation_date is None or period_start is not None or period_end is not None:
        raise DomainValidationError(
            "Point aggregation requires an exact observation date."
        )
    eligible = tuple(
        row
        for row in observations
        if _visible_by_cutoff(row, as_of)
        and row.industry_id == industry_id
        and row.sub_industry_id == sub_industry_id
        and row.signal_type is policy.signal_type
        and row.observation_date == observation_date
        and row.period_start == period_start
        and row.period_end == period_end
    )
    if len({row.region_code for row in eligible}) != len(eligible):
        raise DomainValidationError(
            "Revision selection must yield at most one observation per region."
        )
    if len({row.source_id for row in eligible}) > 1:
        raise DomainValidationError("Source mixing is not allowed in an aggregate.")
    if eligible and len({(row.unit_code, row.currency_code) for row in eligible}) > 1:
        raise DomainValidationError("Unit or currency mismatch in aggregate inputs.")
    if any(
        (row.unit_code, row.currency_code) != (requested_unit, requested_currency)
        for row in eligible
    ):
        raise DomainValidationError("Requested unit or currency mismatches inputs.")
    if any(
        row.unit_code is IndustrySignalUnit.INDEX
        for row in eligible
        if policy.operation is AggregationOperation.SUM
    ):
        raise DomainValidationError("INDEX observations are not additive in v1.")
    _validate_classification_compatibility(eligible)
    return eligible


def _visible_by_cutoff(observation: IndustrySignalObservation, as_of: datetime) -> bool:
    temporal_end = observation.period_end or observation.observation_date
    return (
        observation.available_at <= as_of
        and temporal_end is not None
        and temporal_end <= as_of.date()
    )


def _validate_capacity_observations(
    capacities: tuple[IndustrySignalObservation, ...],
    industry_id: int,
    sub_industry_id: int | None,
    observation_date: date | None,
    as_of: datetime,
    measures: tuple[IndustrySignalObservation, ...],
) -> tuple[IndustrySignalObservation, ...]:
    if (
        not measures
        or measures[0].signal_type is not IndustrySignalType.CAPACITY_UTILIZATION
    ):
        return ()
    eligible = tuple(
        row
        for row in capacities
        if row.available_at <= as_of
        and row.observation_date is not None
        and row.observation_date <= as_of.date()
        and row.industry_id == industry_id
        and row.sub_industry_id == sub_industry_id
        and row.signal_type is IndustrySignalType.CAPACITY
        and row.observation_date == observation_date
    )
    if len({row.region_code for row in eligible}) != len(eligible):
        raise DomainValidationError("Capacity revision selection is ambiguous.")
    if len({row.source_id for row in (*measures, *eligible)}) > 1:
        raise DomainValidationError("Capacity and utilization sources must match.")
    if len({row.unit_code for row in eligible}) > 1:
        raise DomainValidationError("Capacity units must match.")
    _validate_classification_compatibility((*measures, *eligible))
    return eligible


def _validate_classification_compatibility(
    observations: tuple[IndustrySignalObservation, ...],
) -> None:
    states = {row.classification_version_id is not None for row in observations}
    versions = {row.classification_version_id for row in observations}
    if len(states) > 1 or len(versions) > 1:
        raise DomainValidationError(
            "Classification mapping/version provenance is incompatible."
        )


def _sum_value(
    observations: tuple[IndustrySignalObservation, ...],
    regions: tuple[str, ...],
) -> tuple[
    Decimal | None,
    tuple[IndustrySignalAggregateContributor, ...],
    tuple[str, ...],
    int,
    int | None,
]:
    by_region = {row.region_code: row for row in observations}
    contributors: list[IndustrySignalAggregateContributor] = []
    missing: list[str] = []
    values: list[Decimal] = []
    for region_code in regions:
        row = by_region.get(region_code)
        if row is None:
            missing.append(f"No PIT-eligible observation for region {region_code}.")
            continue
        if row.value is not None:
            included = True
            reason = None
            values.append(row.value)
        else:
            included = False
            reason = row.missing_reason
            missing.append(reason or f"Value missing for region {region_code}.")
        contributors.append(
            _contributor(row, AggregateInputRole.MEASURE, included, reason)
        )
    if values:
        try:
            with localcontext() as context:
                context.prec = _SUM_CONTEXT_PRECISION
                total = _checked_result(sum(values, Decimal(0)))
        except DecimalException as exc:
            raise DomainValidationError(
                "Decimal SUM failed at supported precision."
            ) from exc
    else:
        total = None
    return (
        total,
        tuple(contributors),
        tuple(missing),
        len(values),
        observations[0].source_id if observations else None,
    )


def _weighted_value(
    measures: tuple[IndustrySignalObservation, ...],
    capacities: tuple[IndustrySignalObservation, ...],
    regions: tuple[str, ...],
) -> tuple[
    Decimal | None,
    tuple[IndustrySignalAggregateContributor, ...],
    tuple[str, ...],
    int,
    int | None,
]:
    measure_by_region = {row.region_code: row for row in measures}
    capacity_by_region = {row.region_code: row for row in capacities}
    contributors: list[IndustrySignalAggregateContributor] = []
    missing: list[str] = []
    weighted: list[tuple[Decimal, Decimal]] = []
    for region_code in regions:
        measure = measure_by_region.get(region_code)
        if measure is None:
            missing.append(f"No PIT-eligible utilization for region {region_code}.")
            continue
        if measure.value is None:
            reason = measure.missing_reason or f"Utilization missing for {region_code}."
            missing.append(reason)
            contributors.append(
                _contributor(measure, AggregateInputRole.MEASURE, False, reason)
            )
            continue
        capacity = capacity_by_region.get(region_code)
        if capacity is None or capacity.value is None:
            reason = (
                f"Compatible capacity unavailable for utilization in {region_code}."
            )
            missing.append(reason)
            contributors.append(
                _contributor(measure, AggregateInputRole.MEASURE, False, reason)
            )
            continue
        if capacity.value <= 0:
            raise DomainValidationError("Capacity weights must be greater than zero.")
        weighted.append((measure.value, capacity.value))
        contributors.append(
            _contributor(
                measure,
                AggregateInputRole.MEASURE,
                True,
                None,
                calculation_weight=capacity.value,
            )
        )
        contributors.append(
            _contributor(capacity, AggregateInputRole.CAPACITY_WEIGHT, True, None)
        )
    if weighted:
        try:
            with localcontext() as context:
                context.prec = 60
                denominator = sum((weight for _, weight in weighted), Decimal(0))
                numerator = sum(
                    (utilization * weight for utilization, weight in weighted),
                    Decimal(0),
                )
                total = _checked_result(numerator / denominator)
        except DecimalException as exc:
            raise DomainValidationError(
                "Decimal capacity-weighted calculation failed."
            ) from exc
    else:
        total = None
    source_id = measures[0].source_id if measures else None
    return total, tuple(contributors), tuple(missing), len(weighted), source_id


def _checked_result(value: Decimal) -> Decimal:
    if not value.is_finite():
        raise DomainValidationError("Aggregate result must be a finite Decimal.")
    try:
        with localcontext() as context:
            context.prec = 60
            rounded = value.quantize(_RESULT_QUANTUM, rounding=ROUND_HALF_EVEN)
    except DecimalException as exc:
        raise DomainValidationError(
            "Aggregate result cannot fit NUMERIC(38, 12)."
        ) from exc
    integer_digits = max(rounded.adjusted() + 1, 0) if rounded else 0
    if integer_digits > _MAX_INTEGER_DIGITS:
        raise DomainValidationError("Aggregate exceeds NUMERIC(38, 12) precision.")
    return rounded


def _contributor(
    observation: IndustrySignalObservation,
    role: AggregateInputRole,
    included: bool,
    reason: str | None,
    calculation_weight: Decimal | None = None,
) -> IndustrySignalAggregateContributor:
    return IndustrySignalAggregateContributor(
        observation_id=observation.id or 0,
        source_id=observation.source_id,
        revision_number=observation.revision_number,
        region_code=observation.region_code,
        observation_date=observation.observation_date,
        period_start=observation.period_start,
        period_end=observation.period_end,
        publication_date=observation.publication_date,
        publication_datetime=observation.publication_datetime,
        available_at=observation.available_at,
        collected_at=observation.collected_at,
        source_reference=observation.source_reference,
        role=role,
        value=observation.value,
        unit_code=observation.unit_code,
        currency_code=observation.currency_code,
        classification_version_id=observation.classification_version_id,
        classification_mapping_id=observation.classification_mapping_id,
        included=included,
        calculation_weight=calculation_weight,
        exclusion_reason=reason,
    )
