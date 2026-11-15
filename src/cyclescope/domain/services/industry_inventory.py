"""Conservative point-in-time industry inventory cycle analysis."""

from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, DecimalException, localcontext

from cyclescope.domain.entities.industry_inventory import (
    IndustryInventoryClassification as Classification,
)
from cyclescope.domain.entities.industry_inventory import (
    IndustryInventoryConfig,
    IndustryInventoryInputReference,
    IndustryInventorySnapshot,
    IndustryInventoryTrend,
)
from cyclescope.domain.entities.industry_inventory import (
    IndustryInventoryStatus as Status,
)
from cyclescope.domain.entities.industry_signal import (
    IndustrySignalType,
)
from cyclescope.domain.entities.industry_signal_aggregate import (
    AggregateInputRole,
    AggregateScopeRole,
    AggregateStatus,
    IndustrySignalAggregateSnapshot,
)
from cyclescope.domain.exceptions import DomainValidationError

_QUANTUM = Decimal("0.000000000001")


def _date_year_ago(value: date) -> date | None:
    """Return exact calendar anniversary; never substitute Feb 28 for Feb 29."""
    try:
        return value.replace(year=value.year - 1)
    except ValueError:
        return None


def _ratio_change(current: Decimal, prior: Decimal) -> Decimal:
    if prior == 0:
        raise DomainValidationError(
            "YoY growth is unavailable when prior inventory is zero."
        )
    try:
        with localcontext() as context:
            context.prec = 80
            return (current / prior) - Decimal(1)
    except DecimalException as exc:
        raise DomainValidationError("Inventory growth arithmetic failed.") from exc


def _checked(value: Decimal) -> Decimal:
    """Round once at the NUMERIC(38, 12) persistence boundary."""
    try:
        with localcontext() as context:
            context.prec = 80
            rounded = value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)
    except DecimalException as exc:
        raise DomainValidationError(
            "Industry inventory result exceeds precision."
        ) from exc
    parts = rounded.as_tuple()
    if (
        not isinstance(parts.exponent, int)
        or max(len(parts.digits) + parts.exponent, 0) > 26
    ):
        raise DomainValidationError(
            "Industry inventory result exceeds NUMERIC(38, 12)."
        )
    return rounded


def _subtract(left: Decimal, right: Decimal) -> Decimal:
    try:
        with localcontext() as context:
            context.prec = 80
            return _checked(left - right)
    except DecimalException as exc:
        raise DomainValidationError("Industry inventory arithmetic failed.") from exc


def _signature(row: IndustrySignalAggregateSnapshot) -> tuple[object, ...]:
    included = tuple(item for item in row.contributors if item.included)
    scopes = tuple(
        sorted(
            (scope.region_id, scope.region_code)
            for scope in row.requested_scopes
            if scope.role is AggregateScopeRole.CONSTITUENT
        )
    )
    classifications = tuple(
        sorted(
            {
                (item.classification_version_id, item.classification_mapping_id)
                for item in included
            },
            key=lambda pair: (pair[0] or 0, pair[1] or 0),
        )
    )
    sources = tuple(sorted({item.source_id for item in included}))
    return (
        row.industry_id,
        row.sub_industry_id,
        row.aggregate_region_id,
        row.aggregate_region_code,
        scopes,
        row.source_id,
        sources,
        row.unit_code,
        row.currency_code,
        classifications,
    )


def _eligible(
    row: IndustrySignalAggregateSnapshot,
    *,
    as_of: datetime,
    industry_id: int,
    sub_industry_id: int | None,
    aggregate_region_code: str,
    requested_scope: tuple[tuple[int, str], ...],
    source_id: int | None,
) -> bool:
    if row.id is None or row.industry_id != industry_id:
        return False
    if (
        row.sub_industry_id != sub_industry_id
        or row.status is AggregateStatus.INSUFFICIENT_DATA
    ):
        return False
    if row.aggregate_region_code != aggregate_region_code:
        return False
    if row.as_of > as_of or not row.scope_complete:
        return False
    constituents = tuple(
        sorted(
            (scope.region_id, scope.region_code)
            for scope in row.requested_scopes
            if scope.role is AggregateScopeRole.CONSTITUENT
        )
    )
    if constituents != requested_scope:
        return False
    if source_id is not None and row.source_id != source_id:
        return False
    if row.source_id is None:
        return False
    if any(
        item.included
        and (
            item.available_at > as_of
            or item.source_id != row.source_id
            or (
                item.observation_date is not None
                and item.observation_date > as_of.date()
            )
            or (item.period_end is not None and item.period_end > as_of.date())
        )
        for item in row.contributors
    ):
        return False
    if row.temporal_kind.value == "POINT":
        return row.observation_date is not None and row.observation_date <= as_of.date()
    return row.period_end is not None and row.period_end <= as_of.date()


def _latest_by_date(
    rows: list[IndustrySignalAggregateSnapshot],
) -> dict[date, IndustrySignalAggregateSnapshot]:
    result: dict[date, IndustrySignalAggregateSnapshot] = {}
    for row in sorted(rows, key=lambda item: (item.as_of, item.id or 0)):
        key = (
            row.observation_date if row.observation_date is not None else row.period_end
        )
        if key is not None:
            result[key] = row
    return result


def _actual_regions(
    row: IndustrySignalAggregateSnapshot,
) -> tuple[tuple[int, str], ...]:
    scope_ids = {
        scope.region_code: scope.region_id
        for scope in row.requested_scopes
        if scope.role is AggregateScopeRole.CONSTITUENT
    }
    codes = {
        item.region_code
        for item in row.contributors
        if item.included and item.role is AggregateInputRole.MEASURE
    }
    if not codes.issubset(scope_ids):
        raise DomainValidationError(
            "Included measurement region is outside the persisted aggregate scope."
        )
    return tuple(sorted((scope_ids[code], code) for code in codes))


def _expected_interval(
    earlier: date,
    later: date,
    months: int | None,
) -> bool:
    """Accept configured month cadence, preserving equal day or month-end dates."""
    if months is None:
        return False
    month_delta = (later.year - earlier.year) * 12 + later.month - earlier.month
    if month_delta != months or later <= earlier:
        return False
    earlier_is_month_end = (earlier + timedelta(days=1)).day == 1
    later_is_month_end = (later + timedelta(days=1)).day == 1
    return (earlier.day == later.day) or (earlier_is_month_end and later_is_month_end)


def _reference(
    row: IndustrySignalAggregateSnapshot,
    role: str,
    *,
    included: bool = True,
    exclusion_reason: str | None = None,
) -> IndustryInventoryInputReference:
    assert row.id is not None
    return IndustryInventoryInputReference(
        aggregate_id=row.id,
        role=role,
        observation_date=row.observation_date,
        period_start=row.period_start,
        period_end=row.period_end,
        source_id=row.source_id,
        available_at=max(
            (item.available_at for item in row.contributors if item.included),
            default=row.as_of,
        ),
        contributor_revisions=tuple(
            sorted(
                (item.observation_id, item.source_id, item.revision_number)
                for item in row.contributors
                if item.included and item.role is AggregateInputRole.MEASURE
            )
        ),
        contributing_regions=_actual_regions(row),
        coverage=row.coverage_ratio,
        included=included,
        exclusion_reason=exclusion_reason,
    )


def calculate_industry_inventory(
    *,
    aggregates: tuple[IndustrySignalAggregateSnapshot, ...],
    industry_id: int,
    aggregate_region_code: str,
    requested_scope: tuple[tuple[int, str], ...],
    as_of: datetime,
    calculated_at: datetime,
    config: IndustryInventoryConfig,
    sub_industry_id: int | None = None,
    source_id: int | None = None,
) -> IndustryInventorySnapshot:
    """Analyze an exact cohort without re-aggregating raw signals."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise DomainValidationError("as_of must be timezone-aware.")
    if calculated_at.tzinfo is None or calculated_at.utcoffset() is None:
        raise DomainValidationError("calculated_at must be timezone-aware.")
    as_of = as_of.astimezone(UTC)
    calculated_at = calculated_at.astimezone(UTC)
    scope = tuple(sorted(requested_scope))
    if not scope or len(scope) != len(set(scope)):
        raise DomainValidationError(
            "Requested region scope must be unique and non-empty."
        )

    candidate_rows = [
        row
        for row in aggregates
        if _eligible(
            row,
            as_of=as_of,
            industry_id=industry_id,
            sub_industry_id=sub_industry_id,
            aggregate_region_code=aggregate_region_code,
            requested_scope=scope,
            source_id=source_id,
        )
    ]
    inventory_rows = [
        r for r in candidate_rows if r.signal_type is IndustrySignalType.INVENTORY
    ]
    if not inventory_rows:
        raise DomainValidationError("No eligible industry inventory aggregate exists.")
    signatures = {_signature(row) for row in inventory_rows}
    if len(signatures) != 1:
        raise DomainValidationError(
            "Multiple source/classification cohorts require explicit selection."
        )
    signature = next(iter(signatures))
    cohort = [row for row in candidate_rows if _signature(row) == signature]
    inventory_by_date = _latest_by_date(
        [r for r in cohort if r.signal_type is IndustrySignalType.INVENTORY]
    )
    current_date = max(inventory_by_date)
    current = inventory_by_date[current_date]
    prior_date_candidate = max(
        (day for day in inventory_by_date if day < current_date), default=None
    )
    prior_candidate = (
        inventory_by_date.get(prior_date_candidate)
        if prior_date_candidate is not None
        else None
    )
    anniversary = _date_year_ago(current_date)
    year_prior_candidate = (
        inventory_by_date.get(anniversary) if anniversary is not None else None
    )
    prior_anniversary = (
        _date_year_ago(prior_date_candidate)
        if prior_date_candidate is not None
        else None
    )
    prior_year_prior_candidate = (
        inventory_by_date.get(prior_anniversary)
        if prior_anniversary is not None
        else None
    )

    reasons: list[str] = list(current.missing_reasons)
    current_regions = _actual_regions(current)
    current_coverage = current.coverage_ratio
    current_composition_known = bool(current_regions) and current_coverage is not None
    if not current_composition_known:
        reasons.append(
            "Current inventory has unknown or empty actual regional "
            "composition/coverage."
        )

    def composition_ok(
        row: IndustrySignalAggregateSnapshot | None, role: str
    ) -> tuple[bool, str | None]:
        if row is None:
            return False, f"{role} aggregate is unavailable."
        if not current_composition_known:
            return (
                False,
                f"{role} cannot be validated against unknown current composition.",
            )
        if _actual_regions(row) != current_regions:
            return (
                False,
                f"{role} excluded: actual contributing regions differ from "
                "current inventory.",
            )
        if row.coverage_ratio is None or row.coverage_ratio != current_coverage:
            return (
                False,
                f"{role} excluded: coverage differs from current inventory "
                "or is unknown.",
            )
        return True, None

    interval_months = config.expected_observation_interval_months
    prior_interval_ok = prior_date_candidate is not None and _expected_interval(
        prior_date_candidate, current_date, interval_months
    )
    prior_composition_ok, prior_composition_reason = composition_ok(
        prior_candidate, "Previous inventory"
    )
    prior = prior_candidate if prior_interval_ok and prior_composition_ok else None
    prior_exclusion_reason = None
    if prior_candidate is not None and not prior_interval_ok:
        prior_exclusion_reason = (
            "Previous inventory excluded: observation interval does not match "
            "the configured cadence."
        )
        reasons.append(prior_exclusion_reason)
    if prior_candidate is not None and not prior_composition_ok:
        prior_exclusion_reason = prior_composition_reason or (
            "Previous inventory composition is incompatible."
        )
        reasons.append(prior_exclusion_reason)

    year_prior_composition_ok, year_prior_reason = composition_ok(
        year_prior_candidate, "Year-prior inventory"
    )
    year_prior = year_prior_candidate if year_prior_composition_ok else None
    if year_prior_candidate is None:
        reasons.append(
            "Exact calendar-anniversary inventory observation is unavailable."
        )
    elif not year_prior_composition_ok:
        reasons.append(
            year_prior_reason or "Year-prior inventory composition is incompatible."
        )

    prior_year_prior_composition_ok, prior_year_prior_reason = composition_ok(
        prior_year_prior_candidate, "Previous-year-prior inventory"
    )
    prior_year_prior = (
        prior_year_prior_candidate if prior_year_prior_composition_ok else None
    )
    if prior_year_prior_candidate is not None and not prior_year_prior_composition_ok:
        reasons.append(
            prior_year_prior_reason
            or "Previous-year-prior inventory composition is incompatible."
        )
    for row in aggregates:
        if (
            row.signal_type
            not in {IndustrySignalType.PRODUCTION, IndustrySignalType.SHIPMENTS}
            or row.period_end != current_date
            or row.as_of > as_of
        ):
            continue
        row_scope = tuple(
            sorted(
                (item.region_id, item.region_code)
                for item in row.requested_scopes
                if item.role is AggregateScopeRole.CONSTITUENT
            )
        )
        if row_scope != scope or row.aggregate_region_code != aggregate_region_code:
            continue
        if row.status is AggregateStatus.INSUFFICIENT_DATA:
            reasons.extend(
                f"{row.signal_type.value} aggregate unavailable: {reason}"
                for reason in row.missing_reasons
            )
        elif row.source_id != current.source_id or _signature(row) != signature:
            reasons.append(
                f"{row.signal_type.value} excluded due to source, unit, currency, "
                "or classification incompatibility."
            )
    current_value = current.value
    prior_value = prior.value if prior is not None else None
    absolute_change = (
        _subtract(current_value, prior_value)
        if current_value is not None and prior_value is not None
        else None
    )
    yoy = None
    yoy_raw = None
    if year_prior is None or current_value is None or year_prior.value is None:
        pass
    elif year_prior.value == 0:
        reasons.append(
            "YoY growth is unavailable because prior-year inventory is zero."
        )
    else:
        yoy_raw = _ratio_change(current_value, year_prior.value)
        yoy = _checked(yoy_raw)
    prior_yoy = None
    prior_yoy_raw = None
    if (
        prior is not None
        and prior_year_prior is not None
        and prior.value is not None
        and prior_year_prior.value is not None
    ):
        if prior_year_prior.value != 0:
            prior_yoy_raw = _ratio_change(prior.value, prior_year_prior.value)
            prior_yoy = _checked(prior_yoy_raw)
        else:
            reasons.append(
                "Previous comparable YoY unavailable: prior denominator is zero."
            )
    elif prior is None or prior_year_prior is None:
        reasons.append("Previous comparable YoY is unavailable.")
    acceleration = (
        _subtract(yoy_raw, prior_yoy_raw)
        if (
            yoy_raw is not None
            and prior_yoy_raw is not None
            and prior_date_candidate is not None
            and interval_months is not None
            and _expected_interval(prior_date_candidate, current_date, interval_months)
            and year_prior is not None
            and prior_year_prior is not None
            and prior_year_prior.observation_date is not None
            and year_prior.observation_date is not None
            and _expected_interval(
                prior_year_prior.observation_date,
                year_prior.observation_date,
                interval_months,
            )
        )
        else None
    )
    if yoy_raw is not None and prior_yoy_raw is not None and acceleration is None:
        reasons.append(
            "Growth acceleration is unavailable: adjacent observations do not "
            "match the configured interval."
        )

    productions = [
        r
        for r in cohort
        if r.signal_type is IndustrySignalType.PRODUCTION
        and r.period_end == current_date
    ]
    shipments = [
        r
        for r in cohort
        if r.signal_type is IndustrySignalType.SHIPMENTS
        and r.period_end == current_date
    ]
    production_candidate = max(
        productions, key=lambda r: (r.as_of, r.id or 0), default=None
    )
    shipment_candidate = max(
        shipments, key=lambda r: (r.as_of, r.id or 0), default=None
    )
    production_composition_ok, production_reason = composition_ok(
        production_candidate, "Production"
    )
    shipment_composition_ok, shipment_reason = composition_ok(
        shipment_candidate, "Shipments"
    )
    production = production_candidate if production_composition_ok else None
    shipment = shipment_candidate if shipment_composition_ok else None
    if production_candidate is not None and not production_composition_ok:
        reasons.append(production_reason or "Production composition is incompatible.")
    if shipment_candidate is not None and not shipment_composition_ok:
        reasons.append(shipment_reason or "Shipments composition is incompatible.")
    gap = None
    if (
        production is not None
        and shipment is not None
        and production.period_start == shipment.period_start
        and production.value is not None
        and shipment.value is not None
    ):
        gap = _subtract(production.value, shipment.value)
    else:
        reasons.append(
            "Production and shipments are unavailable for an exactly matching period."
        )

    classification = _classify(
        current_value=current_value,
        absolute_change=absolute_change,
        yoy=yoy_raw,
        prior_yoy=prior_yoy_raw,
        acceleration=acceleration,
        gap=gap,
        config=config,
    )
    trend = (
        IndustryInventoryTrend.UNKNOWN
        if absolute_change is None
        else IndustryInventoryTrend.INCREASING
        if absolute_change > 0
        else IndustryInventoryTrend.DECREASING
        if absolute_change < 0
        else IndustryInventoryTrend.STABLE
    )
    coverage = current.coverage_ratio
    required_missing = current_value is None or yoy is None
    if required_missing:
        status = Status.INSUFFICIENT_DATA
        classification = Classification.UNKNOWN
        confidence = None
    else:
        status = (
            Status.AVAILABLE
            if (
                coverage == 1
                and current_regions == scope
                and prior_yoy is not None
                and gap is not None
                and absolute_change is not None
            )
            else Status.PARTIAL
        )
        evidence = Decimal(1)
        if prior_yoy is None:
            evidence -= Decimal("0.20")
        if gap is None:
            evidence -= Decimal("0.20")
        if absolute_change is None:
            evidence -= Decimal("0.10")
        confidence = (coverage or Decimal(0)) * max(evidence, Decimal(0))
        if coverage is None or coverage < config.minimum_coverage:
            status = Status.INSUFFICIENT_DATA
            classification = Classification.UNKNOWN
            confidence = None
            reasons.append("Inventory region coverage is below the configured minimum.")
    refs: list[IndustryInventoryInputReference] = []
    refs.append(_reference(current, "CURRENT_INVENTORY"))
    for optional_row, role, accepted, exclusion_reason in (
        (prior_candidate, "PRIOR_INVENTORY", prior is not None, prior_exclusion_reason),
        (
            year_prior_candidate,
            "YEAR_PRIOR_INVENTORY",
            year_prior is not None,
            None if year_prior is not None else year_prior_reason,
        ),
        (
            prior_year_prior_candidate,
            "PRIOR_YEAR_PRIOR_INVENTORY",
            prior_year_prior is not None,
            None if prior_year_prior is not None else prior_year_prior_reason,
        ),
        (
            production_candidate,
            "PRODUCTION",
            production is not None,
            None if production is not None else production_reason,
        ),
        (
            shipment_candidate,
            "SHIPMENTS",
            shipment is not None,
            None if shipment is not None else shipment_reason,
        ),
    ):
        if optional_row is not None:
            refs.append(
                _reference(
                    optional_row,
                    role,
                    included=accepted,
                    exclusion_reason=exclusion_reason,
                )
            )
    contributing_regions = current_regions
    return IndustryInventorySnapshot(
        industry_id=industry_id,
        sub_industry_id=sub_industry_id,
        aggregate_region_code=aggregate_region_code,
        source_id=current.source_id,
        unit_code=current.unit_code.value,
        currency_code=current.currency_code,
        observation_date=current_date,
        as_of=as_of,
        calculated_at=calculated_at,
        classification=classification,
        trend=trend,
        status=status,
        inventory_value=current_value,
        prior_inventory_value=prior_value,
        absolute_change=absolute_change,
        yoy_growth=yoy,
        prior_yoy_growth=prior_yoy,
        growth_acceleration=acceleration,
        production_value=production.value if production else None,
        shipments_value=shipment.value if shipment else None,
        production_shipment_gap=gap,
        coverage=coverage,
        confidence=confidence,
        config=config,
        requested_scope=scope,
        contributing_regions=contributing_regions,
        input_references=tuple(refs),
        unavailable_reasons=tuple(dict.fromkeys(reasons)),
    )


def _classify(
    *,
    current_value: Decimal | None,
    absolute_change: Decimal | None,
    yoy: Decimal | None,
    prior_yoy: Decimal | None,
    acceleration: Decimal | None,
    gap: Decimal | None,
    config: IndustryInventoryConfig,
) -> Classification:
    if current_value is None or yoy is None:
        return Classification.UNKNOWN
    try:
        with localcontext() as context:
            context.prec = 80
            gap_tolerance = abs(current_value) * config.gap_ratio_tolerance
    except DecimalException as exc:
        raise DomainValidationError(
            "Inventory gap tolerance arithmetic failed."
        ) from exc
    if (
        absolute_change is not None
        and absolute_change < 0
        and yoy < 0
        and gap is not None
        and gap < -gap_tolerance
    ):
        return Classification.DRAWDOWN
    if (
        absolute_change is not None
        and absolute_change > 0
        and prior_yoy is not None
        and prior_yoy <= config.normalization_prior_yoy
        and yoy > prior_yoy
        and yoy <= config.normalization_growth_ceiling
        and gap is not None
        and abs(gap) <= gap_tolerance
    ):
        return Classification.NORMALIZATION
    if (
        absolute_change is not None
        and absolute_change > 0
        and yoy >= config.rapid_accumulation_yoy
        and gap is not None
        and gap > gap_tolerance
    ):
        return Classification.RAPID_ACCUMULATION
    if (
        yoy > 0
        and acceleration is not None
        and acceleration < -config.stable_growth_tolerance
    ):
        return Classification.DECELERATING
    if (
        absolute_change is not None
        and absolute_change > 0
        and yoy >= config.accumulation_yoy
        and gap is not None
        and gap >= -gap_tolerance
    ):
        return Classification.ACCUMULATION
    return Classification.UNKNOWN
