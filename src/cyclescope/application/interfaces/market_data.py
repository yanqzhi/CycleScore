"""Provider-independent acquisition ports."""

from typing import Protocol

from cyclescope.application.dto.market_data import (
    FxRateRequest,
    HistoricalPriceRequest,
    RawDailyPriceRecord,
    RawFxRateRecord,
)


class HistoricalPriceProvider(Protocol):
    """Acquire normalized daily price records for a market-data request."""

    def fetch_historical_prices(
        self, request: HistoricalPriceRequest
    ) -> tuple[RawDailyPriceRecord, ...]:
        """Return common records; provider-specific parsing stays in its adapter."""


class FxRateProvider(Protocol):
    """Acquire normalized FX records for a market-data request."""

    def fetch_fx_rates(self, request: FxRateRequest) -> tuple[RawFxRateRecord, ...]:
        """Return common records; provider-specific parsing stays in its adapter."""


class MarketDataProvider(HistoricalPriceProvider, FxRateProvider, Protocol):
    """Combined provider boundary for adapters offering both feeds."""
