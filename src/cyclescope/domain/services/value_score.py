"""Provider-independent Value Score component formulas and aggregation."""

from datetime import UTC, datetime
from decimal import ROUND_HALF_EVEN, Decimal, localcontext

from cyclescope.domain.entities.daily_price import DailyPrice
from cyclescope.domain.entities.value_score import (
    ValueScore,
    ValueScoreComponent,
    ValueScoreComponentCode,
    ValueScoreComponentStatus,
    ValueScoreConfidence,
    ValueScoreConfig,
    ValueScoreInputReference,
    ValueScoreMeasure,
    ValueScoreStatus,
)
from cyclescope.domain.exceptions import DomainValidationError


def percentile_score(percentile: Decimal) -> Decimal:
    """Map lower valuation percentiles to higher cheapness scores."""
    if not percentile.is_finite() or not 0 <= percentile <= 100:
        raise DomainValidationError("Valuation percentile must be in [0, 100].")
    return Decimal(100) - percentile


def score_historical_price(
    prices: tuple[DailyPrice, ...],
    *,
    as_of: datetime,
    selected_source_id: int | None,
    use_adjusted_close: bool,
    minimum_observations: int,
) -> ValueScoreComponent:
    """ECDF rank of the current comparable closing-price series."""
    component = ValueScoreComponentCode.HISTORICAL_PRICE
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise DomainValidationError("Value Score as_of must be timezone-aware.")
    cutoff = as_of.astimezone(UTC)
    eligible = tuple(
        row
        for row in prices
        if row.available_at <= cutoff and row.observation_date <= cutoff.date()
    )
    sources = {row.source_id for row in eligible}
    if selected_source_id is not None:
        eligible = tuple(row for row in eligible if row.source_id == selected_source_id)
    elif len(sources) > 1:
        return _unavailable(
            component,
            "A market_source_id is required when historical price sources differ.",
        )
    field = "adjusted_close" if use_adjusted_close else "close"
    comparable = tuple(row for row in eligible if getattr(row, field) is not None)
    comparable = tuple(
        row
        for row in comparable
        if getattr(row, field) is not None and getattr(row, field) > 0
    )
    if len(comparable) < minimum_observations:
        return _unavailable(
            component,
            f"Only {len(comparable)} positive {field} observations; "
            f"{minimum_observations} are required.",
        )
    latest = max(comparable, key=lambda row: (row.observation_date, row.id or 0))
    current = getattr(latest, field)
    assert current is not None
    ordered = tuple(sorted(getattr(row, field) for row in comparable))
    rank = (
        Decimal(sum(value <= current for value in ordered))
        * Decimal(100)
        / Decimal(len(ordered))
    ).quantize(Decimal("0.0000001"), rounding=ROUND_HALF_EVEN)
    score = percentile_score(rank)
    references = tuple(
        ValueScoreInputReference(
            record_type="DAILY_PRICE",
            record_id=row.id or 0,
            source_id=row.source_id,
            revision_number=row.revision_number,
            available_at=row.available_at,
            observation_date=row.observation_date,
            security_id=row.security_id,
        )
        for row in comparable
        if row.id is not None
    )
    measure = ValueScoreMeasure(
        code="HISTORICAL_PRICE_PERCENTILE",
        value=rank,
        unit="PERCENTILE",
        score=score,
        reason=(
            "A low price percentile describes price history only and does not "
            "establish undervaluation."
        ),
    )
    return ValueScoreComponent(
        code=component,
        status=ValueScoreComponentStatus.AVAILABLE,
        score=score,
        reason="Historical price rank; it is not a valuation-multiple rank.",
        measures=(measure,),
        input_references=references,
    )


def score_percentile_family(
    component: ValueScoreComponentCode,
    percentiles: tuple[tuple[str, Decimal | None, str | None], ...],
    references: tuple[ValueScoreInputReference, ...],
    exclusion_reasons: tuple[str, ...] = (),
) -> ValueScoreComponent:
    """Average available 100-minus-percentile measures without zero filling."""
    measures = []
    scores = []
    for code, percentile, reason in percentiles:
        if percentile is None:
            measures.append(
                ValueScoreMeasure(
                    code=code,
                    value=None,
                    unit="PERCENTILE",
                    score=None,
                    reason=reason or "Historical percentile is unavailable.",
                )
            )
            continue
        score = percentile_score(percentile)
        scores.append(score)
        measures.append(
            ValueScoreMeasure(
                code=code,
                value=percentile,
                unit="PERCENTILE",
                score=score,
            )
        )
    if not scores:
        return _unavailable(
            component,
            "No comparable historical valuation percentile is available.",
            measures=tuple(measures),
            references=references,
            exclusion_reasons=exclusion_reasons,
        )
    score = _mean(scores)
    missing = len(scores) != len(percentiles)
    coverage = Decimal(len(scores)) / Decimal(len(percentiles))
    return ValueScoreComponent(
        code=component,
        status=(
            ValueScoreComponentStatus.PARTIAL
            if missing
            else ValueScoreComponentStatus.AVAILABLE
        ),
        score=score,
        reason="One or more submetrics are unavailable." if missing else None,
        measures=tuple(measures),
        input_references=references,
        exclusion_reasons=exclusion_reasons,
        coverage=coverage,
    )


def score_debt_to_equity(
    *,
    short_term_debt: Decimal | None,
    long_term_debt: Decimal | None,
    total_equity: Decimal | None,
    maximum_ratio: Decimal,
    references: tuple[ValueScoreInputReference, ...],
) -> ValueScoreComponent:
    """Score leverage linearly from 100 at zero debt to 0 at the configured cap."""
    component = ValueScoreComponentCode.BALANCE_SHEET
    if short_term_debt is None or long_term_debt is None or total_equity is None:
        return _unavailable(
            component,
            "Debt and total equity are required for Debt / Equity.",
            references=references,
        )
    if total_equity <= 0:
        return _invalid(
            component,
            "Total equity is zero or negative; leverage quality is not scoreable.",
            references=references,
        )
    if short_term_debt < 0 or long_term_debt < 0:
        return _invalid(
            component, "Debt inputs must not be negative.", references=references
        )
    debt_to_equity = (short_term_debt + long_term_debt) / total_equity
    normalized = max(Decimal(0), Decimal(1) - debt_to_equity / maximum_ratio)
    score = (normalized * Decimal(100)).quantize(
        Decimal("0.0000001"), rounding=ROUND_HALF_EVEN
    )
    measure = ValueScoreMeasure(
        code="DEBT_TO_EQUITY",
        value=debt_to_equity,
        unit="MULTIPLE",
        score=score,
        reason=f"Linear leverage scale; zero at {maximum_ratio}x or higher.",
    )
    return ValueScoreComponent(
        code=component,
        status=ValueScoreComponentStatus.AVAILABLE,
        score=score,
        reason="Debt / Equity is the only balance-sheet submetric used.",
        measures=(measure,),
        input_references=references,
    )


def score_peer_relative(
    values: tuple[tuple[str, Decimal, Decimal], ...],
    *,
    peer_security_ids: tuple[int, ...],
    references: tuple[ValueScoreInputReference, ...],
    expected_submetrics: int = 3,
    unavailable_reasons: tuple[tuple[str, str], ...] = (),
    excluded_peer_reasons: tuple[tuple[int, str], ...] = (),
) -> ValueScoreComponent:
    """Compare each company multiple with a deterministic peer median.

    Each tuple is ``(metric code, company multiple, peer median)``. The score
    is ``100 * peer_median / (company_multiple + peer_median)``; equality is 50.
    """
    if expected_submetrics < 1:
        raise DomainValidationError("expected_submetrics must be positive.")
    measures = []
    scores = []
    for code, reason in unavailable_reasons:
        measures.append(ValueScoreMeasure(code, None, "MULTIPLE", None, reason))
    for code, company_value, peer_median in values:
        if company_value <= 0 or peer_median <= 0:
            measures.append(
                ValueScoreMeasure(
                    code=code,
                    value=None,
                    unit="MULTIPLE",
                    score=None,
                    reason="Company and peer median multiples must be positive.",
                )
            )
            continue
        score = (Decimal(100) * peer_median / (company_value + peer_median)).quantize(
            Decimal("0.0000001"), rounding=ROUND_HALF_EVEN
        )
        scores.append(score)
        measures.append(
            ValueScoreMeasure(
                code=code,
                value=company_value / peer_median,
                unit="COMPANY_TO_PEER_MEDIAN",
                score=score,
            )
        )
    if not scores:
        return _unavailable(
            ValueScoreComponentCode.RELATIVE_VALUATION,
            "No valid comparable-company multiple is available.",
            measures=tuple(measures),
            references=references,
            peers=peer_security_ids,
            exclusion_reasons=tuple(reason for _, reason in excluded_peer_reasons),
            excluded_peer_reasons=excluded_peer_reasons,
        )
    coverage = Decimal(len(scores)) / Decimal(expected_submetrics)
    return ValueScoreComponent(
        code=ValueScoreComponentCode.RELATIVE_VALUATION,
        status=(
            ValueScoreComponentStatus.PARTIAL
            if coverage < 1
            else ValueScoreComponentStatus.AVAILABLE
        ),
        score=_mean(scores),
        reason=(
            "One or more relative multiples are unavailable." if coverage < 1 else None
        ),
        measures=tuple(measures),
        input_references=references,
        peer_security_ids=peer_security_ids,
        coverage=coverage,
        exclusion_reasons=tuple(reason for _, reason in excluded_peer_reasons),
        excluded_peer_reasons=excluded_peer_reasons,
    )


def finalize_value_score(
    *,
    security_id: int,
    company_id: int,
    as_of: datetime,
    components: tuple[ValueScoreComponent, ...],
    config: ValueScoreConfig,
) -> ValueScore:
    """Redistribute weights only after the configured coverage minimum is met."""
    weights = config.weight_map
    if any(component.coverage is None for component in components):
        raise DomainValidationError(
            "Cannot aggregate a component with unknown legacy coverage."
        )
    covered_weight = sum(
        (
            weights[component.code] * _known_coverage(component)
            for component in components
        ),
        Decimal(0),
    )
    finalized = tuple(
        ValueScoreComponent(
            code=component.code,
            status=component.status,
            score=component.score,
            reason=component.reason,
            measures=component.measures,
            input_references=component.input_references,
            peer_security_ids=component.peer_security_ids,
            original_weight=weights[component.code],
            effective_weight=(
                weights[component.code] * _known_coverage(component) / covered_weight
                if component.score is not None and covered_weight > 0
                else Decimal(0)
            ),
            exclusion_reasons=component.exclusion_reasons,
            excluded_peer_reasons=component.excluded_peer_reasons,
            coverage=component.coverage,
        )
        for component in components
    )
    coverage = covered_weight
    if coverage == 0 or coverage < config.minimum_coverage:
        status = ValueScoreStatus.INSUFFICIENT_DATA
        score = None
        confidence = ValueScoreConfidence.INSUFFICIENT
        reason: str | None = (
            f"Available component weight {coverage} is below the minimum "
            f"coverage {config.minimum_coverage}."
        )
        finalized = tuple(
            ValueScoreComponent(
                code=item.code,
                status=item.status,
                score=item.score,
                reason=item.reason,
                measures=item.measures,
                input_references=item.input_references,
                peer_security_ids=item.peer_security_ids,
                original_weight=item.original_weight,
                effective_weight=Decimal(0),
                exclusion_reasons=item.exclusion_reasons,
                excluded_peer_reasons=item.excluded_peer_reasons,
                coverage=item.coverage,
            )
            for item in finalized
        )
    else:
        with localcontext() as context:
            context.prec = 40
            score = sum(
                (
                    item.score * item.effective_weight
                    for item in finalized
                    if item.score is not None
                ),
                Decimal(0),
            ).quantize(Decimal("0.0000001"), rounding=ROUND_HALF_EVEN)
        status = (
            ValueScoreStatus.AVAILABLE
            if coverage == Decimal(1)
            else ValueScoreStatus.PARTIAL
        )
        confidence = (
            ValueScoreConfidence.HIGH
            if coverage >= config.high_confidence_coverage
            else ValueScoreConfidence.MEDIUM
            if coverage >= config.medium_confidence_coverage
            else ValueScoreConfidence.LOW
        )
        reason = (
            None
            if status == ValueScoreStatus.AVAILABLE
            else "Some components are unavailable."
        )

    reference_rows = tuple(
        reference for item in finalized for reference in item.input_references
    )
    if any(
        reference.available_at > as_of.astimezone(UTC) for reference in reference_rows
    ):
        raise DomainValidationError("A Value Score input was unavailable at as_of.")
    return ValueScore(
        security_id=security_id,
        company_id=company_id,
        as_of=as_of,
        score=score,
        coverage=coverage,
        status=status,
        confidence=confidence,
        config_version=config.version,
        config_snapshot=config.snapshot(),
        components=finalized,
        status_reason=reason,
    )


def _mean(values: list[Decimal]) -> Decimal:
    with localcontext() as context:
        context.prec = 40
        return (sum(values, Decimal(0)) / Decimal(len(values))).quantize(
            Decimal("0.0000001"), rounding=ROUND_HALF_EVEN
        )


def _known_coverage(component: ValueScoreComponent) -> Decimal:
    if component.coverage is None:
        raise DomainValidationError("Component coverage is unknown.")
    return component.coverage


def _unavailable(
    code: ValueScoreComponentCode,
    reason: str,
    *,
    measures: tuple[ValueScoreMeasure, ...] = (),
    references: tuple[ValueScoreInputReference, ...] = (),
    peers: tuple[int, ...] = (),
    exclusion_reasons: tuple[str, ...] = (),
    excluded_peer_reasons: tuple[tuple[int, str], ...] = (),
) -> ValueScoreComponent:
    return ValueScoreComponent(
        code=code,
        status=ValueScoreComponentStatus.UNAVAILABLE,
        score=None,
        reason=reason,
        measures=measures,
        input_references=references,
        peer_security_ids=peers,
        exclusion_reasons=exclusion_reasons,
        excluded_peer_reasons=excluded_peer_reasons,
        coverage=Decimal(0),
    )


def _invalid(
    code: ValueScoreComponentCode,
    reason: str,
    *,
    references: tuple[ValueScoreInputReference, ...] = (),
) -> ValueScoreComponent:
    return ValueScoreComponent(
        code=code,
        status=ValueScoreComponentStatus.INVALID_INPUT,
        score=None,
        reason=reason,
        input_references=references,
        coverage=Decimal(0),
    )
