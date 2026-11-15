"""Deterministic earnings-cycle scoring independent of persistence/frameworks."""

from datetime import UTC, datetime
from decimal import Decimal, localcontext

from cyclescope.domain.entities.cycle_score import (
    CyclePhase,
    CycleScore,
    CycleScoreComponent,
    CycleScoreComponentCode,
    CycleScoreComponentStatus,
    CycleScoreConfidence,
    CycleScoreConfig,
    CycleScoreObservation,
    CycleScoreStatus,
    clamp,
    quantize_score,
)
from cyclescope.domain.exceptions import DomainValidationError


def analyze_cycle_score(
    *,
    company_id: int,
    security_id: int | None,
    as_of: datetime,
    observations: tuple[CycleScoreObservation, ...],
    window_start_fiscal_year: int | None,
    window_end_fiscal_year: int | None,
    currency: str | None,
    source_id: int | None,
    normalized_earnings_result_id: int,
    config: CycleScoreConfig,
) -> CycleScore:
    """Analyze eligible FY observations without filling missing years with zero."""
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise DomainValidationError("as_of must be timezone-aware.")
    cutoff = as_of.astimezone(UTC)
    if (window_start_fiscal_year is None) != (window_end_fiscal_year is None):
        raise DomainValidationError("Fiscal-year window boundaries are incomplete.")
    ordered = tuple(sorted(observations, key=lambda item: item.fiscal_year))
    years = [item.fiscal_year for item in ordered]
    if len(years) != len(set(years)):
        raise DomainValidationError("Cycle Score contains duplicate fiscal years.")
    if ordered:
        if window_start_fiscal_year is None or window_end_fiscal_year is None:
            raise DomainValidationError(
                "Observed earnings require fiscal-year window boundaries."
            )
        if window_start_fiscal_year > window_end_fiscal_year:
            raise DomainValidationError("Fiscal-year window is invalid.")
        source_ids = {item.source_id for item in ordered}
        currencies = {item.currency for item in ordered}
        versions = {item.calculation_version for item in ordered}
        if len(source_ids) != 1 or len(currencies) != 1 or len(versions) != 1:
            raise DomainValidationError(
                "Cycle Score observations mix incompatible source metadata."
            )
        if source_id is not None and source_ids != {source_id}:
            raise DomainValidationError(
                "Cycle Score observations do not match the requested source."
            )
        if currency is not None and currencies != {currency}:
            raise DomainValidationError("Cycle Score observations mix currencies.")
        for observation in ordered:
            if (
                not window_start_fiscal_year
                <= observation.fiscal_year
                <= (window_end_fiscal_year)
            ):
                raise DomainValidationError(
                    "Cycle Score observation is outside its fiscal-year window."
                )
            if observation.period_end > cutoff.date():
                raise DomainValidationError(
                    "Cycle Score observation period ends after as_of."
                )
            for reference in observation.references:
                if (
                    reference.available_at > cutoff
                    or reference.period_end > cutoff.date()
                ):
                    raise DomainValidationError(
                        "Cycle Score input is not eligible at as_of."
                    )
                if (
                    reference.source_id != observation.source_id
                    or reference.fiscal_year != observation.fiscal_year
                    or reference.normalized_earnings_result_id
                    != normalized_earnings_result_id
                    or reference.period_end != observation.period_end
                    or reference.item_code != "OPERATING_PROFIT"
                    or reference.fiscal_period != "FY"
                ):
                    raise DomainValidationError(
                        "Cycle Score input reference conflicts with its observation."
                    )
    expected_years = (
        window_end_fiscal_year - window_start_fiscal_year + 1
        if window_start_fiscal_year is not None and window_end_fiscal_year is not None
        else None
    )
    coverage = (
        (Decimal(len(ordered)) / Decimal(expected_years)).quantize(Decimal("0.0000001"))
        if expected_years
        else None
    )
    refs = tuple(reference for row in ordered for reference in row.references)
    sufficient = (
        len(ordered) >= config.minimum_observations
        and coverage is not None
        and coverage >= config.minimum_coverage
    )
    if not sufficient:
        reason = (
            f"{len(ordered)} annual operating-profit observations with coverage "
            f"{coverage if coverage is not None else 'unknown'}; at least "
            f"{config.minimum_observations} observations and "
            f"{config.minimum_coverage} coverage are required."
        )
        components = tuple(
            CycleScoreComponent(
                code,
                CycleScoreComponentStatus.INSUFFICIENT_DATA,
                None,
                None,
                coverage,
                reason,
            )
            for code in CycleScoreComponentCode
        )
        return CycleScore(
            company_id=company_id,
            security_id=security_id,
            as_of=cutoff,
            score=None,
            status=CycleScoreStatus.INSUFFICIENT_DATA,
            phase=CyclePhase.UNKNOWN,
            phase_reason=reason,
            confidence=CycleScoreConfidence.INSUFFICIENT,
            coverage=coverage,
            currency=currency,
            source_id=source_id,
            normalized_earnings_result_id=normalized_earnings_result_id,
            calculation_version=config.version,
            config_snapshot=config.snapshot(),
            components=components,
            input_references=refs,
            status_reason=reason,
        )

    scale = max((abs(row.value) for row in ordered), default=Decimal(0))
    overall_slope = _slope(ordered)
    recent = ordered[-config.recent_observation_count :]
    recent_slope = _slope(recent)
    split = len(ordered) // 2
    earlier_slope = _slope(ordered[: split + 1])
    recent_half_slope = _slope(ordered[split:])
    with localcontext() as context:
        context.prec = 50
        momentum = _normalized(overall_slope, scale)
        recent_momentum = _normalized(recent_slope, scale)
        acceleration = _normalized(recent_half_slope - earlier_slope, scale)
    position = _historical_position(ordered)
    recent_confirmation = _confirmation(recent, recent_slope)
    phase, phase_reason = _classify_phase(
        ordered=ordered,
        overall_momentum=momentum,
        recent_momentum=recent_momentum,
        acceleration=acceleration,
        position=position,
        confirmation=recent_confirmation,
        config=config,
    )
    scores = {
        CycleScoreComponentCode.EARNINGS_MOMENTUM: _direction_score(
            recent_momentum, config.momentum_full_scale
        ),
        CycleScoreComponentCode.EARNINGS_ACCELERATION: _direction_score(
            acceleration, config.acceleration_full_scale
        ),
        CycleScoreComponentCode.HISTORICAL_POSITION: config.phase_score_map[phase],
        CycleScoreComponentCode.TREND_CONFIRMATION: _confirmation_score(
            recent_momentum, recent_confirmation
        ),
    }
    values = {
        CycleScoreComponentCode.EARNINGS_MOMENTUM: recent_momentum,
        CycleScoreComponentCode.EARNINGS_ACCELERATION: acceleration,
        CycleScoreComponentCode.HISTORICAL_POSITION: position,
        CycleScoreComponentCode.TREND_CONFIRMATION: recent_confirmation,
    }
    components = tuple(
        CycleScoreComponent(
            code,
            CycleScoreComponentStatus.AVAILABLE,
            quantize_score(scores[code]),
            values[code],
            coverage,
            (
                "Phase is unknown; configured neutral phase score is used."
                if code == CycleScoreComponentCode.HISTORICAL_POSITION
                and phase == CyclePhase.UNKNOWN
                else None
            ),
        )
        for code, _ in config.weights
    )
    with localcontext() as context:
        context.prec = 50
        score = quantize_score(
            sum(
                (scores[code] * weight for code, weight in config.weights),
                Decimal(0),
            )
        )
    confidence = _confidence(len(ordered), coverage, config)
    status = (
        CycleScoreStatus.PARTIAL
        if phase == CyclePhase.UNKNOWN
        else CycleScoreStatus.AVAILABLE
    )
    if status == CycleScoreStatus.PARTIAL:
        confidence = CycleScoreConfidence.LOW
    return CycleScore(
        company_id=company_id,
        security_id=security_id,
        as_of=cutoff,
        score=score,
        status=status,
        phase=phase,
        phase_reason=phase_reason,
        confidence=confidence,
        coverage=coverage,
        currency=currency,
        source_id=source_id,
        normalized_earnings_result_id=normalized_earnings_result_id,
        calculation_version=config.version,
        config_snapshot=config.snapshot(),
        components=components,
        input_references=refs,
    )


def _slope(rows: tuple[CycleScoreObservation, ...]) -> Decimal:
    if len(rows) < 2:
        return Decimal(0)
    with localcontext() as context:
        context.prec = 50
        count = Decimal(len(rows))
        mean_year = sum((Decimal(row.fiscal_year) for row in rows), Decimal(0)) / count
        mean_value = sum((row.value for row in rows), Decimal(0)) / count
        numerator = sum(
            (
                (Decimal(row.fiscal_year) - mean_year) * (row.value - mean_value)
                for row in rows
            ),
            Decimal(0),
        )
        denominator = sum(
            ((Decimal(row.fiscal_year) - mean_year) ** 2 for row in rows), Decimal(0)
        )
        return numerator / denominator if denominator else Decimal(0)


def _normalized(value: Decimal, scale: Decimal) -> Decimal:
    return value / scale if scale else Decimal(0)


def _historical_position(rows: tuple[CycleScoreObservation, ...]) -> Decimal:
    low = min(row.value for row in rows)
    high = max(row.value for row in rows)
    if high == low:
        return Decimal("0.5")
    return (rows[-1].value - low) / (high - low)


def _confirmation(rows: tuple[CycleScoreObservation, ...], slope: Decimal) -> Decimal:
    if len(rows) < 2 or slope == 0:
        return Decimal("0.5")
    rising = slope > 0
    intervals = [
        (right.value - left.value) / Decimal(right.fiscal_year - left.fiscal_year)
        for left, right in zip(rows, rows[1:], strict=False)
    ]
    supportive = sum(
        (1 for change in intervals if (change > 0 if rising else change < 0)), 0
    )
    return Decimal(supportive) / Decimal(len(intervals))


def _direction_score(value: Decimal, full_scale: Decimal) -> Decimal:
    return Decimal(50) + Decimal(50) * clamp(value / full_scale)


def _confirmation_score(momentum: Decimal, confirmation: Decimal) -> Decimal:
    if momentum > 0:
        return Decimal(50) + Decimal(50) * confirmation
    if momentum < 0:
        return Decimal(50) - Decimal(50) * confirmation
    return Decimal(50)


def _classify_phase(
    *,
    ordered: tuple[CycleScoreObservation, ...],
    overall_momentum: Decimal,
    recent_momentum: Decimal,
    acceleration: Decimal,
    position: Decimal,
    confirmation: Decimal,
    config: CycleScoreConfig,
) -> tuple[CyclePhase, str]:
    recent = ordered[-config.recent_observation_count :]
    recent_changes = tuple(
        right.value - left.value
        for left, right in zip(recent, recent[1:], strict=False)
    )
    trough_changes = recent_changes[-config.trough_confirmation_changes :]
    confirmed_stabilization = (
        len(trough_changes) == config.trough_confirmation_changes
        and all(change >= 0 for change in trough_changes)
        and any(change > 0 for change in trough_changes)
    )
    if (
        position <= config.low_earnings_position
        and overall_momentum < -config.momentum_deadband
        and abs(recent_momentum) <= config.momentum_deadband
        and acceleration > config.acceleration_deadband
        and confirmed_stabilization
    ):
        return (
            CyclePhase.TROUGH,
            "Earnings remain near their low after confirmed stabilization and "
            "positive acceleration; low level alone is not enough.",
        )
    if confirmation < config.minimum_trend_confirmation:
        return (
            CyclePhase.UNKNOWN,
            "Recent annual observations do not confirm a direction.",
        )
    if recent_momentum > config.momentum_deadband:
        if (
            overall_momentum < -config.momentum_deadband
            and position > config.low_earnings_position
        ):
            return (
                CyclePhase.UNKNOWN,
                "Recent improvement conflicts with the full-window declining trend "
                "outside the low-earnings zone.",
            )
        if position <= config.low_earnings_position:
            return (
                CyclePhase.EARLY_RECOVERY,
                "Earnings are near their historical low and recent operating profit "
                "is improving with trend confirmation.",
            )
        return (
            CyclePhase.EXPANSION,
            "Recent operating profit is improving with trend confirmation.",
        )
    if recent_momentum < -config.momentum_deadband:
        if position >= config.high_earnings_position:
            return (
                CyclePhase.PEAK,
                "Earnings are near their historical high and recent operating profit "
                "is deteriorating with trend confirmation.",
            )
        return (
            CyclePhase.CONTRACTION,
            "Recent operating profit is deteriorating with trend confirmation; a low "
            "historical level alone does not confirm a trough.",
        )
    return (
        CyclePhase.UNKNOWN,
        "Recent earnings momentum is inside the configured deadband.",
    )


def _confidence(
    observations: int, coverage: Decimal | None, config: CycleScoreConfig
) -> CycleScoreConfidence:
    if coverage is None:
        return CycleScoreConfidence.INSUFFICIENT
    if (
        observations >= config.high_confidence_observations
        and coverage >= config.high_confidence_coverage
    ):
        return CycleScoreConfidence.HIGH
    if coverage >= config.medium_confidence_coverage:
        return CycleScoreConfidence.MEDIUM
    return CycleScoreConfidence.LOW
