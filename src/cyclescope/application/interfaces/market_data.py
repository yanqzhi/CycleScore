"""Provider ports for normalized, provider-independent CSV rows."""

from pathlib import Path
from typing import Protocol

from cyclescope.application.dto.market_data import CsvFxRateRecord, CsvPriceRecord


class HistoricalPriceProvider(Protocol):
    """Read daily OHLCV records from a provider-specific source."""

    def read_prices(self, file_path: Path) -> tuple[CsvPriceRecord, ...]:
        """Return raw typed rows; application use cases normalize and validate."""


class FxRateProvider(Protocol):
    """Read FX observations from a provider-specific source."""

    def read_fx_rates(self, file_path: Path) -> tuple[CsvFxRateRecord, ...]:
        """Return raw typed rows; application use cases normalize and validate."""


class MarketDataProvider(HistoricalPriceProvider, FxRateProvider, Protocol):
    """Combined market-data provider boundary for providers offering both feeds."""
