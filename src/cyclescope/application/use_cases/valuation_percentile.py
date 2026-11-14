"""Build PIT daily valuation distributions and persist ECDF snapshots."""

from datetime import UTC, date

from cyclescope.application.dto.normalized_earnings import NormalizedEarningsRequest
from cyclescope.application.dto.valuation import ValuationInputRequest
from cyclescope.application.dto.valuation_percentile import (
    HistoricalValuationPercentileListResponse,
    HistoricalValuationPercentileQuery,
    HistoricalValuationPercentileRequest,
    HistoricalValuationPercentileResponse,
    lookback_start,
)
from cyclescope.application.interfaces.data_quality import (
    TradingCalendar,
    TradingCalendarNotConfigured,
)
from cyclescope.application.use_cases.normalized_earnings import (
    CalculateNormalizedEarnings,
)
from cyclescope.application.use_cases.valuation_inputs import BuildValuationInputs
from cyclescope.domain.entities.normalized_earnings import (
    EarningsMetric,
    NormalizedEarningsResult,
)
from cyclescope.domain.entities.valuation import (
    ValuationMetricCode,
    ValuationMetricValue,
    ValuationResultStatus,
)
from cyclescope.domain.entities.valuation_percentile import (
    HistoricalValuationObservation,
    PercentileMetric,
    ValuationLookbackPeriod,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    ListingRepository,
    NormalizedEarningsRepository,
    SecurityRepository,
    ValuationMetricValueRepository,
    ValuationPercentileRepository,
)
from cyclescope.domain.services.valuation_percentile import (
    calculate_valuation_percentile,
)

_VALUATION_CODE = {
    PercentileMetric.PER: ValuationMetricCode.PER,
    PercentileMetric.PBR: ValuationMetricCode.PBR,
    PercentileMetric.EV_EBITDA: ValuationMetricCode.EV_EBITDA,
}
_NORMALIZED_METRIC = {
    PercentileMetric.NORMALIZED_PER: EarningsMetric.EPS,
    PercentileMetric.NORMALIZED_EV_EBITDA: EarningsMetric.EBITDA,
}


def _normalized_source_match(
    result: NormalizedEarningsResult,
    base: ValuationMetricValue,
    request: HistoricalValuationPercentileRequest,
) -> bool:
    price_sources = {
        reference.source_id
        for reference in result.valuation_input_references
        if reference.record_type == "DAILY_PRICE"
    }
    financial_sources = {
        reference.source_id
        for reference in result.valuation_input_references
        if reference.record_type == "FINANCIAL_LINE"
    }
    if request.market_source_id is not None:
        if price_sources != {request.market_source_id}:
            return False
    elif base.price_source_id is not None and price_sources != {base.price_source_id}:
        return False
    if request.financial_source_id is not None:
        return financial_sources == {request.financial_source_id}
    return not base.financial_source_ids or financial_sources == set(
        base.financial_source_ids
    )


class CalculateHistoricalValuationPercentile:
    """Calculate one metric, rebuilding missing history through Sprint 10."""

    def __init__(
        self,
        securities: SecurityRepository,
        listings: ListingRepository,
        valuation_values: ValuationMetricValueRepository,
        normalized_earnings: NormalizedEarningsRepository,
        results: ValuationPercentileRepository,
        calendar: TradingCalendar,
        valuation_input_builder: BuildValuationInputs,
        normalized_calculator: CalculateNormalizedEarnings,
    ) -> None:
        self._securities = securities
        self._listings = listings
        self._valuation_values = valuation_values
        self._normalized_earnings = normalized_earnings
        self._results = results
        self._calendar = calendar
        self._valuation_input_builder = valuation_input_builder
        self._normalized_calculator = normalized_calculator

    def execute(
        self, request: HistoricalValuationPercentileRequest
    ) -> HistoricalValuationPercentileResponse:
        security = self._securities.get_by_id(request.security_id)
        if security is None:
            raise DomainValidationError("Unknown security.")
        listing_dates = [
            listing.listing_date
            for listing in self._listings.list_by_security(request.security_id)
        ]
        listing_date = min(listing_dates) if listing_dates else None
        cutoff_date = request.as_of.astimezone(UTC).date()
        start = lookback_start(request.lookback_period, request.as_of, listing_date)
        raw = self._load_observations(request, start)
        if request.lookback_period == ValuationLookbackPeriod.AVAILABLE_HISTORY:
            start = start or min(
                (item.observation_date for item in raw), default=cutoff_date
            )
        assert start is not None
        start = min(start, cutoff_date)
        raw = tuple(
            item
            for item in raw
            if start <= item.observation_date <= cutoff_date
            and item.as_of <= request.as_of
            and (
                request.market_source_id is None
                or item.market_source_id == request.market_source_id
            )
            and (
                request.financial_source_id is None
                or item.financial_source_ids == (request.financial_source_id,)
            )
        )
        self._validate_sources(raw, request)
        current = max(
            raw,
            key=lambda item: (
                item.observation_date,
                item.as_of,
                item.snapshot_id or item.normalized_earnings_result_id or 0,
            ),
            default=None,
        )
        currency = current.currency if current else None
        unit = current.unit if current else "RATIO"
        financial_period = current.financial_period if current else None
        calculation_version = current.calculation_version if current else 1
        try:
            sessions = self._calendar.expected_sessions(
                request.calendar_id, start, cutoff_date
            )
            expected = tuple(
                sorted(
                    {session for session in sessions if start <= session <= cutoff_date}
                )
            )
        except TradingCalendarNotConfigured:
            expected = None
        result = calculate_valuation_percentile(
            security_id=request.security_id,
            company_id=security.company_id,
            metric=request.metric,
            lookback_period=request.lookback_period,
            as_of=request.as_of,
            current=current,
            observations=raw,
            expected_sessions=expected,
            currency=currency,
            unit=unit,
            financial_period=financial_period,
            calculation_version=calculation_version,
            policy=request.policy,
        )
        return HistoricalValuationPercentileResponse(self._results.create(result))

    def _load_observations(
        self, request: HistoricalValuationPercentileRequest, start_date: date | None
    ) -> tuple[HistoricalValuationObservation, ...]:
        if request.metric in _VALUATION_CODE:
            valuation_rows = self._valuation_values.list_by_security(
                request.security_id,
                _VALUATION_CODE[request.metric],
                start_date=start_date,
                as_of=request.as_of,
            )
            return tuple(self._from_valuation(row) for row in valuation_rows)
        security = self._securities.get_by_id(request.security_id)
        assert security is not None
        earnings_metric = _NORMALIZED_METRIC[request.metric]
        base_code = (
            ValuationMetricCode.PER
            if request.metric == PercentileMetric.NORMALIZED_PER
            else ValuationMetricCode.EV_EBITDA
        )
        base_rows = self._valuation_values.list_by_security(
            request.security_id,
            base_code,
            start_date=start_date,
            as_of=request.as_of,
        )
        base_rows = [
            row
            for row in base_rows
            if row.as_of.date() == row.observation_date
            and (
                request.market_source_id is None
                or row.price_source_id == request.market_source_id
            )
            and (
                request.financial_source_id is None
                or row.financial_source_ids == (request.financial_source_id,)
            )
        ]
        self._validate_sources(
            tuple(self._from_valuation(row) for row in base_rows), request
        )
        normalized_rows = self._normalized_earnings.list_by_company(
            security.company_id,
            metric=earnings_metric,
            as_of=request.as_of,
            start_date=start_date,
        )
        output: list[HistoricalValuationObservation] = []
        for base in base_rows:
            matches = [
                row
                for row in normalized_rows
                if row.metric == earnings_metric
                and row.as_of == base.as_of
                and row.method == request.normalization_method
                and row.requested_window_years == request.normalization_window_years
                and row.da_sign_convention == request.da_sign_convention
                and _normalized_source_match(row, base, request)
            ]
            selected = max(matches, key=lambda row: row.id or 0, default=None)
            if selected is None:
                inputs = self._valuation_input_builder.execute(
                    ValuationInputRequest(
                        security_id=request.security_id,
                        valuation_date=base.observation_date,
                        as_of=base.as_of,
                        financial_source_id=request.financial_source_id,
                        market_source_id=request.market_source_id,
                    )
                )
                generated = self._normalized_calculator.execute(
                    NormalizedEarningsRequest(
                        company_id=security.company_id,
                        security_id=request.security_id,
                        as_of=base.as_of,
                        window_years=request.normalization_window_years,
                        method=request.normalization_method,
                        da_sign_convention=request.da_sign_convention,
                        source_id=request.financial_source_id,
                        valuation_inputs=inputs,
                    )
                )
                selected = next(
                    row for row in generated if row.metric == earnings_metric
                )
                normalized_rows.extend(generated)
            if selected.normalized_valuation_status is not None:
                output.append(self._from_normalized(selected, base))
        return tuple(output)

    @staticmethod
    def _from_valuation(row: ValuationMetricValue) -> HistoricalValuationObservation:
        return HistoricalValuationObservation(
            observation_date=row.observation_date,
            as_of=row.as_of,
            status=row.status.value,
            value=row.value,
            currency=row.currency,
            unit=row.unit.value,
            financial_period=row.financial_period,
            calculation_version=row.calculation_version,
            market_source_id=row.price_source_id,
            financial_source_ids=row.financial_source_ids,
            snapshot_id=row.id,
            references=row.input_references,
            unavailable_reason=row.unavailable_reason,
        )

    @staticmethod
    def _from_normalized(
        row: NormalizedEarningsResult,
        base: ValuationMetricValue,
    ) -> HistoricalValuationObservation:
        price_refs = tuple(
            reference
            for reference in row.valuation_input_references
            if reference.record_type == "DAILY_PRICE"
        )
        price_date = max(
            (
                reference.observation_date
                for reference in price_refs
                if reference.observation_date
            ),
            default=row.as_of.date(),
        )
        sources = tuple(
            sorted(
                {
                    reference.source_id
                    for reference in row.valuation_input_references
                    if reference.record_type == "FINANCIAL_LINE"
                }
            )
        )
        status = row.normalized_valuation_status or ValuationResultStatus.UNAVAILABLE
        return HistoricalValuationObservation(
            observation_date=price_date,
            as_of=row.as_of,
            status=status.value,
            value=row.normalized_valuation_value,
            currency=row.currency,
            unit="RATIO",
            financial_period=(
                f"NORMALIZED:{row.method.value}:{row.requested_window_years}:"
                f"{row.effective_window_years}"
            ),
            calculation_version=row.calculation_version,
            market_source_id=(
                price_refs[0].source_id if price_refs else base.price_source_id
            ),
            financial_source_ids=sources or base.financial_source_ids,
            snapshot_id=base.id,
            normalized_earnings_result_id=row.id,
            references=row.valuation_input_references,
            unavailable_reason=row.normalized_valuation_reason or row.status_reason,
            exclusion_reason=(
                "Normalized earnings cutoff does not match the market observation date."
                if row.as_of.date() != price_date
                else None
            ),
        )

    @staticmethod
    def _validate_sources(
        observations: tuple[HistoricalValuationObservation, ...],
        request: HistoricalValuationPercentileRequest,
    ) -> None:
        relevant = tuple(
            item
            for item in observations
            if (
                request.market_source_id is None
                or item.market_source_id == request.market_source_id
            )
            and (
                request.financial_source_id is None
                or request.financial_source_id in item.financial_source_ids
            )
        )
        if request.market_source_id is None:
            sources = {
                item.market_source_id for item in relevant if item.market_source_id
            }
            if len(sources) > 1:
                raise DomainValidationError(
                    "market_source_id is required when multiple sources are eligible."
                )
        if request.financial_source_id is None:
            source_sets = {
                item.financial_source_ids
                for item in relevant
                if item.financial_source_ids
            }
            if len(source_sets) > 1:
                raise DomainValidationError(
                    "financial_source_id is required when financial sources differ."
                )


class GetHistoricalValuationPercentiles:
    """Retrieve immutable percentile snapshots at a requested PIT cutoff."""

    def __init__(self, results: ValuationPercentileRepository) -> None:
        self._results = results

    def execute(
        self, request: HistoricalValuationPercentileQuery
    ) -> HistoricalValuationPercentileListResponse:
        return HistoricalValuationPercentileListResponse(
            tuple(
                self._results.list_by_security(request.security_id, as_of=request.as_of)
            )
        )
