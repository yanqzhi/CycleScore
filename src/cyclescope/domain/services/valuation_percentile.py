"""Deterministic ECDF valuation percentile calculation."""

from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from cyclescope.domain.entities.valuation_percentile import (
    HistoricalValuationObservation,
    PercentileConfidence,
    PercentileMethod,
    PercentileMetric,
    PercentileObservationAudit,
    PercentilePolicy,
    ValuationLookbackPeriod,
    ValuationPercentileResult,
    ValuationPercentileStatus,
)


def calculate_valuation_percentile(
    *,
    security_id: int,
    company_id: int,
    metric: PercentileMetric,
    lookback_period: ValuationLookbackPeriod,
    as_of: datetime,
    current: HistoricalValuationObservation | None,
    observations: tuple[HistoricalValuationObservation, ...],
    expected_sessions: tuple[date, ...] | None,
    currency: str | None,
    unit: str,
    financial_period: str | None,
    calculation_version: int,
    policy: PercentilePolicy | None = None,
) -> ValuationPercentileResult:
    """Compare current multiple with eligible daily values using ECDF.

    One latest snapshot per observation date is retained. Exact percentile ties
    count as less than or equal to the current value. Boundaries are therefore
    0% only below every historical value, and 100% at or above the maximum.
    """
    selected_policy = policy or PercentilePolicy()
    audit: list[PercentileObservationAudit] = []
    eligible_by_date: dict[date, list[HistoricalValuationObservation]] = {}
    unique_snapshots: dict[tuple[str, int | str], HistoricalValuationObservation] = {}
    for item in sorted(
        observations,
        key=lambda row: (
            row.observation_date,
            row.as_of,
            row.snapshot_id or 0,
            row.normalized_earnings_result_id or 0,
        ),
    ):
        identity = (
            ("normalized", item.normalized_earnings_result_id)
            if item.normalized_earnings_result_id is not None
            else ("valuation", item.snapshot_id)
            if item.snapshot_id is not None
            else ("anonymous", repr(item))
        )
        if identity in unique_snapshots:
            continue
        unique_snapshots[identity] = item

    for item in unique_snapshots.values():
        pit_reason = item.exclusion_reason or _point_in_time_reason(item)
        if pit_reason:
            audit.append(_audit(item, False, pit_reason))
            continue
        eligible_by_date.setdefault(item.observation_date, []).append(item)

    latest: dict[date, HistoricalValuationObservation] = {}
    for observation_date, snapshots in eligible_by_date.items():
        for superseded in snapshots[:-1]:
            audit.append(
                _audit(superseded, False, "Superseded by a later eligible snapshot.")
            )
        latest[observation_date] = snapshots[-1]

    expected = set(expected_sessions or ())
    valid: list[HistoricalValuationObservation] = []
    for item in latest.values():
        reason = _exclusion_reason(
            item, expected, currency, unit, financial_period, calculation_version
        )
        if reason:
            audit.append(_audit(item, False, reason))
        else:
            valid.append(item)
            audit.append(_audit(item, True, None))
    valid.sort(key=lambda row: row.observation_date)

    current_reason = _current_reason(
        current, currency, unit, financial_period, calculation_version
    )
    if current is not None and current.status != "AVAILABLE":
        status = (
            ValuationPercentileStatus.UNAVAILABLE
            if current.status == "UNAVAILABLE"
            else ValuationPercentileStatus.INSUFFICIENT_DATA
            if current.status == "INSUFFICIENT_DATA"
            else ValuationPercentileStatus.INVALID_INPUT
        )
        status_reason = current_reason
    elif current_reason:
        status = ValuationPercentileStatus.INVALID_INPUT
        status_reason = current_reason
    elif current is None:
        status = ValuationPercentileStatus.INSUFFICIENT_DATA
        status_reason = "No current eligible valuation snapshot is available."
    elif expected_sessions is None:
        status = ValuationPercentileStatus.UNAVAILABLE
        status_reason = "No expected trading sessions are available for coverage."
    elif not expected_sessions:
        status = ValuationPercentileStatus.INSUFFICIENT_DATA
        status_reason = "There are no trading sessions in the requested period."
    elif len(valid) < selected_policy.minimum_observations:
        status = ValuationPercentileStatus.INSUFFICIENT_DATA
        status_reason = (
            f"Only {len(valid)} valid observations; at least "
            f"{selected_policy.minimum_observations} are required."
        )
    else:
        status = ValuationPercentileStatus.AVAILABLE
        status_reason = None

    count = len(valid)
    coverage = (
        (Decimal(count) / Decimal(len(expected_sessions))).quantize(
            Decimal("0.0000001"), rounding=ROUND_HALF_EVEN
        )
        if expected_sessions
        else None
    )
    ordered_values = sorted(item.value for item in valid if item.value is not None)
    median = None
    if ordered_values:
        with localcontext() as context:
            context.prec = 50
            mid = len(ordered_values) // 2
            median = (
                ordered_values[mid]
                if len(ordered_values) % 2
                else (ordered_values[mid - 1] + ordered_values[mid]) / Decimal(2)
            )
            median = median.quantize(
                Decimal("0.000000000001"), rounding=ROUND_HALF_EVEN
            )
    percentile = None
    if status == ValuationPercentileStatus.AVAILABLE and current is not None:
        assert current.value is not None
        percentile = (
            Decimal(sum(value <= current.value for value in ordered_values))
            * Decimal(100)
            / Decimal(count)
        ).quantize(Decimal("0.0000001"), rounding=ROUND_HALF_EVEN)
    confidence = _confidence(count, coverage, selected_policy)
    dates = [item.observation_date for item in observations]
    return ValuationPercentileResult(
        security_id=security_id,
        company_id=company_id,
        metric=metric,
        lookback_period=lookback_period,
        method=PercentileMethod.ECDF,
        as_of=as_of,
        observation_start=min(dates) if dates else None,
        observation_end=max(dates) if dates else None,
        current_value=current.value if current else None,
        percentile=percentile,
        historical_minimum=ordered_values[0] if ordered_values else None,
        historical_maximum=ordered_values[-1] if ordered_values else None,
        historical_median=median,
        valid_observations=count,
        excluded_observations=sum(not item.included for item in audit),
        expected_observations=len(expected_sessions)
        if expected_sessions is not None
        else None,
        coverage_ratio=coverage,
        status=status,
        confidence=confidence,
        data_quality=(
            "CLEAN"
            if not any(not item.included for item in audit)
            else "EXCLUSIONS_PRESENT"
        ),
        currency=currency,
        unit=unit,
        financial_period=financial_period,
        calculation_version=calculation_version,
        status_reason=status_reason,
        observations=tuple(
            sorted(
                audit,
                key=lambda row: (
                    row.observation_date,
                    row.included,
                    row.snapshot_id or 0,
                ),
            )
        ),
    )


def _exclusion_reason(
    item: HistoricalValuationObservation,
    expected: set[date],
    currency: str | None,
    unit: str,
    financial_period: str | None,
    calculation_version: int,
) -> str | None:
    if item.exclusion_reason:
        return item.exclusion_reason
    if item.observation_date not in expected:
        return "Observation date is not an expected trading session."
    if item.status != "AVAILABLE" or item.value is None:
        return item.unavailable_reason or f"Snapshot status is {item.status}."
    if item.value <= 0:
        return "Valuation multiple must be positive."
    if currency is None or item.currency is None:
        return "Historical valuation currency is unavailable."
    if not financial_period or not item.financial_period:
        return "Historical financial-period basis is unavailable."
    if item.currency != currency:
        return "Currency differs from the current valuation."
    if item.unit != unit:
        return "Unit differs from the current valuation."
    if item.financial_period != financial_period:
        return "Financial period basis differs from the current valuation."
    if item.calculation_version != calculation_version:
        return "Calculation version differs from the current valuation."
    return None


def _point_in_time_reason(item: HistoricalValuationObservation) -> str | None:
    if item.as_of.date() != item.observation_date:
        return "Historical snapshot cutoff does not match its observation date."
    if any(reference.available_at > item.as_of for reference in item.references):
        return "An input was not available at the historical snapshot cutoff."
    if any(
        reference.observation_date is not None
        and reference.observation_date > item.observation_date
        for reference in item.references
    ):
        return "A market input is dated after the historical observation."
    return None


def _current_reason(
    current: HistoricalValuationObservation | None,
    currency: str | None,
    unit: str,
    financial_period: str | None,
    calculation_version: int,
) -> str | None:
    if current is None:
        return None
    pit_reason = _point_in_time_reason(current)
    if pit_reason:
        return pit_reason
    if current.status != "AVAILABLE" or current.value is None:
        return current.unavailable_reason or "Current valuation is unavailable."
    if current.value <= 0:
        return "Current valuation must be positive."
    if currency is None:
        return "Current valuation currency is unavailable."
    if not financial_period:
        return "Current financial-period basis is unavailable."
    if current.currency != currency:
        return "Current valuation currency is missing or inconsistent."
    if current.unit != unit:
        return "Current valuation unit is inconsistent."
    if current.financial_period != financial_period:
        return "Current valuation financial period basis is inconsistent."
    if current.calculation_version != calculation_version:
        return "Current valuation calculation version is inconsistent."
    return None


def _audit(
    item: HistoricalValuationObservation, included: bool, reason: str | None
) -> PercentileObservationAudit:
    return PercentileObservationAudit(
        observation_date=item.observation_date,
        value=item.value,
        included=included,
        reason=reason,
        snapshot_id=item.snapshot_id,
        normalized_earnings_result_id=item.normalized_earnings_result_id,
        market_source_id=item.market_source_id,
        financial_source_ids=item.financial_source_ids,
        references=item.references,
    )


def _confidence(
    count: int, coverage: Decimal | None, policy: PercentilePolicy
) -> PercentileConfidence:
    if count == 0:
        return PercentileConfidence.INSUFFICIENT
    if coverage is None or coverage < policy.confidence_coverage:
        return PercentileConfidence.LOW
    if count >= policy.high_observations:
        return PercentileConfidence.HIGH
    if count >= policy.medium_observations:
        return PercentileConfidence.MEDIUM
    return PercentileConfidence.LOW
