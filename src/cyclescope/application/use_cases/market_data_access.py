"""Unified point-in-time read service for prices and FX observations."""

from collections import defaultdict

from cyclescope.application.dto.market_data_access import (
    DataRetrievalStatus,
    FxObservationAsOfRequest,
    FxPeriodRequest,
    FxQueryScope,
    FxRevisionHistoryRequest,
    LatestFxRateRequest,
    LatestPriceRequest,
    MarketDataQueryResult,
    PrecedingFxRatesRequest,
    PrecedingPricesRequest,
    PriceObservationAsOfRequest,
    PricePeriodRequest,
    PriceRevisionHistoryRequest,
    SourceDataAvailability,
)
from cyclescope.application.use_cases.revision_management import (
    MarketDataRevisionManagement,
)
from cyclescope.domain.entities import DailyPrice, FxRate
from cyclescope.domain.repositories.contracts import (
    DailyPriceRepository,
    FxRateRepository,
)
from cyclescope.domain.value_objects.market_data import CurrencyPair, MarketDataPeriod


class MarketDataAccess:
    """Application query facade; repositories enforce the shared PIT selection rules."""

    def __init__(
        self,
        price_repository: DailyPriceRepository,
        fx_repository: FxRateRepository,
    ) -> None:
        self._prices = price_repository
        self._fx = fx_repository
        self._revisions = MarketDataRevisionManagement(price_repository, fx_repository)

    def get_latest_available_prices(
        self, request: LatestPriceRequest
    ) -> MarketDataQueryResult[DailyPrice]:
        rows = self._prices.get_latest_by_source(
            request.scope.security_id, request.as_of, request.scope.source_id
        )
        return MarketDataQueryResult(request.as_of, tuple(rows))

    def get_latest_available_fx_rates(
        self, request: LatestFxRateRequest
    ) -> MarketDataQueryResult[FxRate]:
        rows = self._fx.get_latest_by_source(
            self._pair(request.scope), request.as_of, request.scope.source_id
        )
        return MarketDataQueryResult(request.as_of, tuple(rows))

    def get_prices_by_period_as_of(
        self, request: PricePeriodRequest
    ) -> MarketDataQueryResult[DailyPrice]:
        period = MarketDataPeriod(request.start_date, request.end_date)
        rows = self._prices.get_by_security_and_period(
            request.scope.security_id,
            period,
            request.as_of,
            request.scope.source_id,
        )
        availability = self._price_availability(request, rows)
        return MarketDataQueryResult(
            request.as_of,
            tuple(rows),
            availability,
            request.start_date,
            request.end_date,
        )

    def get_fx_rates_by_period_as_of(
        self, request: FxPeriodRequest
    ) -> MarketDataQueryResult[FxRate]:
        period = MarketDataPeriod(request.start_date, request.end_date)
        rows = self._fx.get_by_pair_and_period(
            self._pair(request.scope),
            period,
            request.as_of,
            request.scope.source_id,
        )
        availability = self._fx_availability(request, rows)
        return MarketDataQueryResult(
            request.as_of,
            tuple(rows),
            availability,
            request.start_date,
            request.end_date,
        )

    def get_preceding_prices(
        self, request: PrecedingPricesRequest
    ) -> MarketDataQueryResult[DailyPrice]:
        rows = self._prices.get_preceding_by_security(
            request.scope.security_id,
            request.before_date,
            request.as_of,
            request.scope.source_id,
            limit_per_source=request.limit_per_source,
        )
        return MarketDataQueryResult(request.as_of, tuple(rows))

    def get_preceding_fx_rates(
        self, request: PrecedingFxRatesRequest
    ) -> MarketDataQueryResult[FxRate]:
        rows = self._fx.get_preceding_by_pair(
            self._pair(request.scope),
            request.before_date,
            request.as_of,
            request.scope.source_id,
            limit_per_source=request.limit_per_source,
        )
        return MarketDataQueryResult(request.as_of, tuple(rows))

    def get_price_observation_as_of(
        self, request: PriceObservationAsOfRequest
    ) -> MarketDataQueryResult[DailyPrice]:
        rows = self._prices.get_by_security_and_period(
            request.scope.security_id,
            MarketDataPeriod(request.observation_date, request.observation_date),
            request.as_of,
            request.scope.source_id,
        )
        return MarketDataQueryResult(request.as_of, tuple(rows))

    def get_fx_observation_as_of(
        self, request: FxObservationAsOfRequest
    ) -> MarketDataQueryResult[FxRate]:
        rows = self._fx.get_by_pair_and_period(
            self._pair(request.scope),
            MarketDataPeriod(request.observation_date, request.observation_date),
            request.as_of,
            request.scope.source_id,
        )
        return MarketDataQueryResult(request.as_of, tuple(rows))

    def get_price_revision_history(
        self, request: PriceRevisionHistoryRequest
    ) -> MarketDataQueryResult[DailyPrice]:
        if request.observation_date > request.as_of.date():
            return MarketDataQueryResult(request.as_of, ())
        source_id = request.scope.source_id
        assert source_id is not None
        rows = self._revisions.price_revisions(
            request.scope.security_id, request.observation_date, source_id
        )
        eligible = tuple(row for row in rows if row.available_at <= request.as_of)
        return MarketDataQueryResult(request.as_of, eligible)

    def get_fx_revision_history(
        self, request: FxRevisionHistoryRequest
    ) -> MarketDataQueryResult[FxRate]:
        if request.observation_date > request.as_of.date():
            return MarketDataQueryResult(request.as_of, ())
        source_id = request.scope.source_id
        assert source_id is not None
        rows = self._revisions.fx_revisions(
            self._pair(request.scope), request.observation_date, source_id
        )
        eligible = tuple(row for row in rows if row.available_at <= request.as_of)
        return MarketDataQueryResult(request.as_of, eligible)

    def _price_availability(
        self,
        request: PricePeriodRequest,
        period_rows: tuple[DailyPrice, ...] | list[DailyPrice],
    ) -> tuple[SourceDataAvailability, ...]:
        latest = self._prices.get_latest_by_source(
            request.scope.security_id, request.as_of, request.scope.source_id
        )
        return self._availability(
            request.scope.source_id,
            latest,
            period_rows,
            request.minimum_observations,
        )

    def _fx_availability(
        self, request: FxPeriodRequest, period_rows: tuple[FxRate, ...] | list[FxRate]
    ) -> tuple[SourceDataAvailability, ...]:
        latest = self._fx.get_latest_by_source(
            self._pair(request.scope), request.as_of, request.scope.source_id
        )
        return self._availability(
            request.scope.source_id,
            latest,
            period_rows,
            request.minimum_observations,
        )

    @staticmethod
    def _availability(
        selected_source: int | None,
        latest: tuple[DailyPrice, ...]
        | tuple[FxRate, ...]
        | list[DailyPrice]
        | list[FxRate],
        period_rows: tuple[DailyPrice, ...]
        | tuple[FxRate, ...]
        | list[DailyPrice]
        | list[FxRate],
        minimum_observations: int,
    ) -> tuple[SourceDataAvailability, ...]:
        latest_by_source = {row.source_id: row for row in latest}
        counts: dict[int, int] = defaultdict(int)
        for row in period_rows:
            counts[row.source_id] += 1
        source_ids = set(latest_by_source) | set(counts)
        if selected_source is not None:
            source_ids.add(selected_source)
        results: list[SourceDataAvailability] = []
        for source_id in sorted(source_ids):
            latest_row = latest_by_source.get(source_id)
            count = counts[source_id]
            status = (
                DataRetrievalStatus.NO_DATA
                if count == 0
                else DataRetrievalStatus.INSUFFICIENT_DATA
                if count < minimum_observations
                else DataRetrievalStatus.AVAILABLE
            )
            results.append(
                SourceDataAvailability(
                    source_id=source_id,
                    latest_observation_date=(
                        latest_row.observation_date if latest_row is not None else None
                    ),
                    latest_available_at=(
                        latest_row.available_at if latest_row is not None else None
                    ),
                    period_observation_count=count,
                    period_contains_data=count > 0,
                    status=status,
                )
            )
        return tuple(results)

    @staticmethod
    def _pair(scope: FxQueryScope) -> CurrencyPair:
        return CurrencyPair(scope.base_currency, scope.quote_currency)
