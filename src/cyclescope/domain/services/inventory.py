"""Deterministic Decimal calculations for annual company inventory."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

from cyclescope.domain.entities.inventory import (
    InventoryAnnualObservation,
    InventoryConfidence,
    InventoryConfig,
    InventoryInputReference,
    InventorySnapshot,
    InventoryStatus,
    InventoryTrend,
)
from cyclescope.domain.exceptions import DomainValidationError


def _annual_period_issue(
    observation: InventoryAnnualObservation, config: InventoryConfig
) -> str | None:
    if observation.period_compatibility_reason is not None:
        return observation.period_compatibility_reason
    if observation.period_start is None:
        return "FY period start is missing; annual comparability cannot be verified."
    duration = (observation.period_end - observation.period_start).days + 1
    if not (
        config.minimum_annual_period_days
        <= duration
        <= config.maximum_annual_period_days
    ):
        return (
            "Incompatible financial periods: FY duration is outside the configured "
            "annual range."
        )
    return None


def _period_comparability_issue(
    previous: InventoryAnnualObservation,
    current: InventoryAnnualObservation,
    config: InventoryConfig,
) -> str | None:
    if previous.fiscal_year + 1 != current.fiscal_year:
        return "Missing opening inventory from the immediately preceding fiscal year."
    previous_issue = _annual_period_issue(previous, config)
    if previous_issue is not None:
        return previous_issue
    current_issue = _annual_period_issue(current, config)
    if current_issue is not None:
        return current_issue
    assert previous.period_start is not None
    assert current.period_start is not None
    if previous.period_end >= current.period_start:
        return "Incompatible financial periods: prior FY overlaps current FY."
    if previous.period_end + timedelta(days=1) != current.period_start:
        return "Incompatible financial periods: a gap exists between FY periods."
    return None


def _divide(numerator: Decimal, denominator: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 80
        return numerator / denominator


def _average(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 80
        return (left + right) / Decimal(2)


def _subtract(left: Decimal, right: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 80
        return left - right


def _trend(
    observations: tuple[InventoryAnnualObservation, ...], config: InventoryConfig
) -> InventoryTrend:
    if observations and (
        observations[-1].closing_inventory is None
        or observations[-1].closing_inventory < 0
        or _annual_period_issue(observations[-1], config) is not None
    ):
        return InventoryTrend.UNKNOWN
    valid = [
        row
        for row in observations
        if row.closing_inventory is not None and row.closing_inventory >= 0
    ]
    if not valid:
        return InventoryTrend.UNKNOWN
    trailing = [valid[-1]]
    for row in reversed(valid[:-1]):
        if _period_comparability_issue(row, trailing[-1], config) is not None:
            break
        trailing.append(row)
    trailing.reverse()
    if len(trailing) < config.minimum_trend_observations:
        return InventoryTrend.UNKNOWN
    growths: list[Decimal] = []
    for previous, current in zip(trailing, trailing[1:], strict=False):
        if previous.closing_inventory is None or current.closing_inventory is None:
            return InventoryTrend.UNKNOWN
        if previous.closing_inventory <= 0:
            return InventoryTrend.UNKNOWN
        growths.append(
            _divide(
                _subtract(current.closing_inventory, previous.closing_inventory),
                previous.closing_inventory,
            )
        )
    threshold = config.stable_growth_threshold
    if all(value > threshold for value in growths):
        return InventoryTrend.INCREASING
    if all(value < -threshold for value in growths):
        return InventoryTrend.DECREASING
    if all(abs(value) <= threshold for value in growths):
        return InventoryTrend.STABLE
    return InventoryTrend.VOLATILE


def calculate_inventory(
    *,
    company_id: int,
    security_id: int | None,
    as_of: datetime,
    observations: tuple[InventoryAnnualObservation, ...],
    config: InventoryConfig | None = None,
) -> tuple[InventorySnapshot, ...]:
    """Build one snapshot per annual observation without filling missing years."""
    config = config or InventoryConfig()
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise DomainValidationError("Inventory as_of must be timezone-aware.")
    cutoff = as_of.astimezone(UTC)
    ordered = tuple(sorted(observations, key=lambda row: row.fiscal_year))
    if len({row.fiscal_year for row in ordered}) != len(ordered):
        raise DomainValidationError("Inventory observations repeat a fiscal year.")
    if any(row.period_end > cutoff.date() for row in ordered):
        raise DomainValidationError("Inventory period end is after as_of.")
    if ordered:
        signatures = {
            (
                row.source_id,
                row.accounting_standard,
                row.consolidation_scope,
                row.currency,
            )
            for row in ordered
        }
        if len(signatures) != 1:
            raise DomainValidationError(
                "Inventory inputs have incompatible sources or basis."
            )
    output = []
    previous: InventoryAnnualObservation | None = None
    for index, row in enumerate(ordered):
        reasons: list[str] = []
        row_period_issue = _annual_period_issue(row, config)
        if row_period_issue is not None:
            reasons.append(row_period_issue)
        closing = row.closing_inventory
        if closing is None:
            reasons.append("Missing closing inventory.")
        elif closing < 0:
            closing = None
            reasons.append("Invalid inventory balance: closing inventory is negative.")
        opening = None
        if previous is None:
            reasons.append("Missing opening inventory from the previous fiscal year.")
        elif (
            period_issue := _period_comparability_issue(previous, row, config)
        ) is not None:
            reasons.append(period_issue)
        elif previous.closing_inventory is None or previous.closing_inventory < 0:
            reasons.append("Previous fiscal-year closing inventory is unavailable.")
        else:
            opening = previous.closing_inventory
        average = None
        if opening is not None and closing is not None:
            average = _average(opening, closing)
            if average <= 0:
                average = None
                reasons.append("Average inventory must be positive.")
        change = None
        growth = None
        if opening is not None and closing is not None:
            change = _subtract(closing, opening)
            if opening > 0:
                growth = _divide(change, opening)
            else:
                reasons.append(
                    "Inventory growth is unavailable when opening inventory is zero."
                )
        cogs = row.cogs
        if cogs is None:
            reasons.append(row.cogs_unavailable_reason or "Missing annual COGS.")
        elif (period_issue := _annual_period_issue(row, config)) is not None:
            cogs = None
            reasons.append(period_issue)
        elif cogs <= 0:
            cogs = None
            reasons.append("Annual COGS must be positive.")
        turnover = None
        dio = None
        if cogs is not None and average is not None:
            turnover = _divide(cogs, average)
            dio = _divide(Decimal(config.days_per_year), turnover)
        else:
            reasons.append(
                "Inventory turnover requires positive COGS and average inventory."
            )

        available_metrics = sum(
            value is not None
            for value in (closing, opening, average, change, growth, turnover, dio)
        )
        refs: list[InventoryInputReference] = []
        for reference in (row.inventory_reference, row.cogs_reference):
            if reference is not None and reference not in refs:
                refs.append(reference)
        # Include each annual closing-balance fact actually used by the trend.
        trailing: list[InventoryAnnualObservation] = [row]
        for candidate in reversed(ordered[:index]):
            if _period_comparability_issue(candidate, trailing[-1], config) is not None:
                break
            trailing.append(candidate)
        for candidate in trailing:
            reference = candidate.inventory_reference
            if reference is not None and reference not in refs:
                refs.append(reference)
        trend = _trend(ordered[: index + 1], config)
        if trend == InventoryTrend.UNKNOWN:
            reasons.append("Insufficient consecutive annual observations for trend.")
        available_metrics += trend != InventoryTrend.UNKNOWN
        coverage = Decimal(available_metrics) / Decimal(8)
        if coverage == 1:
            status = InventoryStatus.AVAILABLE
        elif available_metrics:
            status = InventoryStatus.PARTIAL
        else:
            status = InventoryStatus.INSUFFICIENT_DATA
        confidence = (
            InventoryConfidence.HIGH
            if coverage >= Decimal("0.85")
            else InventoryConfidence.MEDIUM
            if coverage >= Decimal("0.6")
            else InventoryConfidence.LOW
            if coverage > 0
            else InventoryConfidence.INSUFFICIENT
        )
        output.append(
            InventorySnapshot(
                company_id=company_id,
                security_id=security_id,
                as_of=cutoff,
                fiscal_year=row.fiscal_year,
                period_start=row.period_start,
                period_end=row.period_end,
                closing_inventory=closing,
                opening_inventory=opening,
                average_inventory=average,
                cogs=cogs,
                inventory_change=change,
                inventory_growth=growth,
                inventory_turnover=turnover,
                dio=dio,
                trend=trend,
                status=status,
                unavailable_reasons=tuple(dict.fromkeys(reasons)),
                data_coverage=coverage,
                confidence=confidence,
                currency=row.currency,
                source_id=row.source_id,
                calculation_version=config.version,
                config_snapshot=config.snapshot(),
                input_references=tuple(refs),
            )
        )
        previous = row
    return tuple(output)
