"""Application orchestration for point-in-time Value Score snapshots."""

from datetime import UTC, date, datetime
from decimal import Decimal, localcontext

from cyclescope.application.dto.valuation import ValuationInputRequest
from cyclescope.application.dto.valuation_percentile import (
    HistoricalValuationPercentileRequest,
    lookback_start,
)
from cyclescope.application.dto.value_score import (
    CalculateValueScoreRequest,
    HistoricalPriceBasis,
    ValueScoreResponse,
)
from cyclescope.application.use_cases.valuation_inputs import BuildValuationInputs
from cyclescope.application.use_cases.valuation_percentile import (
    CalculateHistoricalValuationPercentile,
)
from cyclescope.domain.entities.company_industry_exposure import (
    CompanyIndustryExposure,
)
from cyclescope.domain.entities.valuation import (
    ValuationInputReference,
    ValuationMetricCode,
    ValuationMetricValue,
)
from cyclescope.domain.entities.valuation_percentile import PercentileMetric
from cyclescope.domain.entities.value_score import (
    ValueScoreComponent,
    ValueScoreComponentCode,
    ValueScoreComponentStatus,
    ValueScoreInputReference,
    ValueScoreMeasure,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    CompanyIndustryExposureRepository,
    DailyPriceRepository,
    SecurityRepository,
    ValuationMetricValueRepository,
    ValueScoreRepository,
)
from cyclescope.domain.services.value_score import (
    finalize_value_score,
    score_debt_to_equity,
    score_historical_price,
    score_peer_relative,
    score_percentile_family,
)
from cyclescope.domain.value_objects.market_data import MarketDataPeriod


class CalculateValueScore:
    """Compose existing PIT valuation services into one immutable score."""

    def __init__(
        self,
        securities: SecurityRepository,
        prices: DailyPriceRepository,
        values: ValuationMetricValueRepository,
        exposures: CompanyIndustryExposureRepository,
        results: ValueScoreRepository,
        percentile_calculator: CalculateHistoricalValuationPercentile,
        valuation_input_builder: BuildValuationInputs,
    ) -> None:
        self._securities = securities
        self._prices = prices
        self._values = values
        self._exposures = exposures
        self._results = results
        self._percentiles = percentile_calculator
        self._input_builder = valuation_input_builder

    def execute(self, request: CalculateValueScoreRequest) -> ValueScoreResponse:
        security = self._securities.get_by_id(request.security_id)
        if security is None:
            raise DomainValidationError("Unknown security.")
        as_of = request.as_of.astimezone(UTC)
        start = lookback_start(request.lookback_period, as_of, None) or date.min
        price_rows = self._prices.get_by_security_and_period(
            request.security_id,
            MarketDataPeriod(start, as_of.date()),
            as_of,
            request.market_source_id,
        )
        price_component = score_historical_price(
            tuple(price_rows),
            as_of=as_of,
            selected_source_id=request.market_source_id,
            use_adjusted_close=request.price_basis
            == HistoricalPriceBasis.ADJUSTED_CLOSE,
            minimum_observations=request.config.minimum_price_observations,
        )

        valuation_rows = []
        valuation_refs: list[ValueScoreInputReference] = []
        valuation_exclusions: list[str] = []
        for metric in (PercentileMetric.PER, PercentileMetric.PBR):
            result = self._percentiles.execute(
                self._percentile_request(request, metric)
            ).result
            valuation_rows.append(
                (metric.value, result.percentile, result.status_reason)
            )
            if result.id:
                valuation_refs.append(
                    ValueScoreInputReference(
                        "VALUATION_PERCENTILE",
                        result.id,
                        result.as_of,
                        security_id=security.id,
                        reference_code=metric.value,
                    ),
                )
            for row in result.observations:
                if row.included:
                    record_id = row.snapshot_id
                    if record_id:
                        valuation_refs.append(
                            ValueScoreInputReference(
                                "VALUATION_SNAPSHOT",
                                record_id,
                                result.as_of,
                                source_id=row.market_source_id,
                                observation_date=row.observation_date,
                                security_id=security.id,
                                reference_code=metric.value,
                            )
                        )
                    valuation_refs.extend(
                        _input_reference(reference, metric.value)
                        for reference in row.references
                    )
                elif row.reason:
                    valuation_exclusions.append(row.reason)
        historical_component = score_percentile_family(
            ValueScoreComponentCode.HISTORICAL_VALUATION,
            tuple(valuation_rows),
            tuple(dict.fromkeys(valuation_refs)),
            tuple(valuation_exclusions),
        )

        normalized_rows = []
        normalized_refs = []
        normalized_exclusions: list[str] = []
        for metric in (
            PercentileMetric.NORMALIZED_PER,
            PercentileMetric.NORMALIZED_EV_EBITDA,
        ):
            result = self._percentiles.execute(
                self._percentile_request(request, metric)
            ).result
            normalized_rows.append(
                (metric.value, result.percentile, result.status_reason)
            )
            if result.id:
                normalized_refs.append(
                    ValueScoreInputReference(
                        "VALUATION_PERCENTILE",
                        result.id,
                        result.as_of,
                        security_id=security.id,
                        reference_code=metric.value,
                    )
                )
            for row in result.observations:
                if row.included:
                    record_id = row.normalized_earnings_result_id or row.snapshot_id
                    if record_id and row.normalized_earnings_result_id:
                        normalized_refs.append(
                            ValueScoreInputReference(
                                "NORMALIZED_EARNINGS",
                                record_id,
                                result.as_of,
                                source_id=row.market_source_id,
                                observation_date=row.observation_date,
                                security_id=security.id,
                                reference_code=metric.value,
                            )
                        )
                    normalized_refs.extend(
                        _input_reference(reference, metric.value)
                        for reference in row.references
                    )
                elif row.reason:
                    normalized_exclusions.append(row.reason)
        normalized_component = score_percentile_family(
            ValueScoreComponentCode.NORMALIZED_EARNINGS_VALUATION,
            tuple(normalized_rows),
            tuple(dict.fromkeys(normalized_refs)),
            tuple(normalized_exclusions),
        )

        inputs = self._input_builder.execute(
            ValuationInputRequest(
                security_id=request.security_id,
                valuation_date=as_of.date(),
                as_of=as_of,
                financial_source_id=request.financial_source_id,
                market_source_id=request.market_source_id,
            )
        )
        balance_refs = tuple(
            ValueScoreInputReference(
                reference.record_type,
                reference.record_id,
                reference.available_at,
                source_id=reference.source_id,
                revision_number=reference.revision_number,
                observation_date=reference.observation_date,
                security_id=request.security_id,
                reference_code=reference.financial_item_code,
            )
            for reference in inputs.input_references
        )
        balance_component = score_debt_to_equity(
            short_term_debt=inputs.short_term_debt,
            long_term_debt=inputs.long_term_debt,
            total_equity=inputs.total_equity,
            maximum_ratio=request.config.maximum_debt_to_equity,
            references=balance_refs,
        )

        cash_component = _unavailable(
            ValueScoreComponentCode.CASH_FLOW_VALUATION,
            "Operating cash flow and CAPEX are not available in standardized inputs; "
            "no proxy or zero is assumed.",
        )
        relative_component = self._relative_component(
            request, security.company_id, as_of
        )
        score = finalize_value_score(
            security_id=request.security_id,
            company_id=security.company_id,
            as_of=as_of,
            components=(
                price_component,
                historical_component,
                normalized_component,
                cash_component,
                balance_component,
                relative_component,
            ),
            config=request.config,
        )
        return ValueScoreResponse(self._results.create(score))

    @staticmethod
    def _percentile_request(
        request: CalculateValueScoreRequest, metric: PercentileMetric
    ) -> HistoricalValuationPercentileRequest:
        return HistoricalValuationPercentileRequest(
            security_id=request.security_id,
            metric=metric,
            lookback_period=request.lookback_period,
            as_of=request.as_of,
            calendar_id=request.calendar_id,
            market_source_id=request.market_source_id,
            financial_source_id=request.financial_source_id,
            normalization_window_years=request.normalization_window_years,
            normalization_method=request.normalization_method,
            da_sign_convention=request.da_sign_convention,
            policy=request.percentile_policy,
        )

    def _relative_component(
        self, request: CalculateValueScoreRequest, company_id: int, as_of: datetime
    ) -> ValueScoreComponent:
        cutoff = as_of.date()
        target = _active_exposures(self._exposures.list_by_company(company_id), cutoff)
        if not target:
            return _unavailable(
                ValueScoreComponentCode.RELATIVE_VALUATION,
                "The target has no active sub-industry exposure.",
                excluded_peer_reasons=tuple(
                    (
                        peer_id,
                        "Target industry exposure is unavailable for compatibility "
                        "checks.",
                    )
                    for peer_id in request.peer_security_ids
                ),
            )
        if not request.peer_security_ids:
            return _unavailable(
                ValueScoreComponentCode.RELATIVE_VALUATION,
                "Explicit peer IDs are required.",
            )
        compatible: list[int] = []
        excluded_peer_reasons: dict[int, str] = {}
        for peer_id in request.peer_security_ids:
            peer = self._securities.get_by_id(peer_id)
            if peer is None:
                excluded_peer_reasons[peer_id] = "Unknown security."
                continue
            peer_exposures = _active_exposures(
                self._exposures.list_by_company(peer.company_id), cutoff
            )
            if set(target) & set(peer_exposures):
                compatible.append(peer_id)
            else:
                excluded_peer_reasons[peer_id] = (
                    "No active sub-industry exposure is shared with the target."
                )
        metric_map = (
            (ValuationMetricCode.PER, "PER"),
            (ValuationMetricCode.PBR, "PBR"),
            (ValuationMetricCode.EV_EBITDA, "EV_EBITDA"),
        )
        values: list[tuple[str, Decimal, Decimal]] = []
        references: list[ValueScoreInputReference] = []
        selected_peers: list[int] = []
        unavailable_reasons: list[tuple[str, str]] = []
        for metric, code in metric_map:
            rows_by_security: dict[int, list[ValuationMetricValue]] = {}
            for peer_id in (request.security_id, *compatible):
                rows = self._values.list_by_security(
                    peer_id, metric, start_date=cutoff, end_date=cutoff, as_of=as_of
                )
                rows = [
                    row
                    for row in rows
                    if row.status.value == "AVAILABLE" and row.value and row.value > 0
                ]
                if request.financial_source_id is not None:
                    rows = [
                        row
                        for row in rows
                        if row.financial_source_ids == (request.financial_source_id,)
                    ]
                else:
                    rows = [row for row in rows if len(row.financial_source_ids) == 1]
                if request.market_source_id is not None:
                    rows = [
                        row
                        for row in rows
                        if row.price_source_id == request.market_source_id
                    ]
                if rows:
                    rows_by_security[peer_id] = rows
            signature_rows = {
                peer_id: [
                    row
                    for row in rows
                    if len(row.financial_source_ids) == 1
                    and row.price_source_id is not None
                ]
                for peer_id, rows in rows_by_security.items()
            }
            target_rows = signature_rows.get(request.security_id, [])
            latest_target_rows: dict[
                tuple[tuple[int, ...], int | None, str | None, str | None, int],
                ValuationMetricValue,
            ] = {}
            for row in target_rows:
                target_key = (
                    row.financial_source_ids,
                    row.price_source_id,
                    row.currency,
                    row.financial_period,
                    row.calculation_version,
                )
                previous = latest_target_rows.get(target_key)
                if previous is None or (row.as_of, row.id or 0) > (
                    previous.as_of,
                    previous.id or 0,
                ):
                    latest_target_rows[target_key] = row
            target_rows = list(latest_target_rows.values())
            candidate_cohorts = []
            for target_row in target_rows:
                signature = (
                    target_row.financial_source_ids,
                    target_row.price_source_id,
                )
                matching_by_peer = {}
                for peer_id in compatible:
                    matching = [
                        row
                        for row in signature_rows.get(peer_id, [])
                        if (row.financial_source_ids, row.price_source_id) == signature
                        and row.currency == target_row.currency
                        and row.financial_period == target_row.financial_period
                        and row.calculation_version == target_row.calculation_version
                    ]
                    if matching:
                        matching_by_peer[peer_id] = max(
                            matching, key=lambda row: (row.as_of, row.id or 0)
                        )
                candidate_cohorts.append((target_row, signature, matching_by_peer))
            # A source cohort is ranked by its eligible peer count. Ties use
            # ascending source IDs and then comparable metric metadata.
            eligible_cohorts = [
                candidate
                for candidate in candidate_cohorts
                if len(candidate[2]) >= request.config.minimum_peer_count
            ]
            if eligible_cohorts:
                target_row, signature, peers_by_id = min(
                    eligible_cohorts,
                    key=lambda candidate: (
                        -len(candidate[2]),
                        candidate[1][0],
                        candidate[1][1],
                        candidate[0].currency or "",
                        candidate[0].financial_period or "",
                        candidate[0].calculation_version,
                        candidate[0].as_of,
                        candidate[0].id or 0,
                    ),
                )
                comparable = tuple(
                    peers_by_id[peer_id] for peer_id in sorted(peers_by_id)
                )
                peer_median = _decimal_median(
                    [row.value for row in comparable if row.value is not None]
                )
                company_value = target_row.value
                if company_value is not None:
                    values.append((code, company_value, peer_median))
                    selected_peers.extend(peers_by_id)
                    for row in (target_row, *comparable):
                        if row.id:
                            references.append(
                                ValueScoreInputReference(
                                    "VALUATION_SNAPSHOT",
                                    row.id,
                                    row.as_of,
                                    source_id=row.price_source_id,
                                    revision_number=row.price_revision_number,
                                    observation_date=row.observation_date,
                                    security_id=row.security_id,
                                    reference_code=code,
                                    financial_source_ids=row.financial_source_ids,
                                )
                            )
                    for peer_id in compatible:
                        if peer_id not in peers_by_id:
                            excluded_peer_reasons[peer_id] = (
                                f"Excluded from selected {code} cohort: no eligible "
                                "matching source, currency, period, or calculation "
                                "version."
                            )
            else:
                unavailable_reasons.append(
                    (
                        code,
                        "No source-, currency-, period-, and version-compatible "
                        "peer sample met the configured minimum.",
                    )
                )
                # Record candidate source-specific counts for every peer. No
                # source set is merged when no cohort reaches the minimum.
                for peer_id in compatible:
                    excluded_peer_reasons.setdefault(
                        peer_id,
                        f"Excluded from {code}: no eligible comparable source cohort "
                        f"reached {request.config.minimum_peer_count} peers.",
                    )
        return score_peer_relative(
            tuple(values),
            peer_security_ids=tuple(sorted(set(selected_peers))),
            references=tuple(references),
            expected_submetrics=len(metric_map),
            unavailable_reasons=tuple(unavailable_reasons),
            excluded_peer_reasons=tuple(sorted(excluded_peer_reasons.items())),
        )


def _active_exposures(rows: list[CompanyIndustryExposure], cutoff: date) -> set[int]:
    return {
        row.sub_industry_id
        for row in rows
        if (row.valid_from is None or row.valid_from <= cutoff)
        and (row.valid_to is None or row.valid_to >= cutoff)
        and row.revenue_share > 0
    }


def _input_reference(
    reference: ValuationInputReference, metric_code: str
) -> ValueScoreInputReference:
    return ValueScoreInputReference(
        record_type=reference.record_type,
        record_id=reference.record_id,
        available_at=reference.available_at,
        source_id=reference.source_id,
        revision_number=reference.revision_number,
        observation_date=reference.observation_date,
        reference_code=metric_code,
    )


def _decimal_median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    with localcontext() as context:
        context.prec = 50
        return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def _unavailable(
    code: ValueScoreComponentCode,
    reason: str,
    *,
    excluded_peer_reasons: tuple[tuple[int, str], ...] = (),
) -> ValueScoreComponent:
    return ValueScoreComponent(
        code,
        ValueScoreComponentStatus.UNAVAILABLE,
        None,
        reason,
        measures=(ValueScoreMeasure(code.value, None, "N/A", None, reason),),
        excluded_peer_reasons=excluded_peer_reasons,
    )
