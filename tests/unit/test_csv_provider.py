"""CSV market-data provider parsing tests."""

import inspect
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import get_type_hints

import pytest

from cyclescope.application.dto.market_data import FxRateRequest, HistoricalPriceRequest
from cyclescope.application.interfaces.market_data import HistoricalPriceProvider
from cyclescope.infrastructure.market_data.csv_provider import (
    CsvFormatError,
    CsvHistoricalMarketDataProvider,
)


def test_csv_price_and_fx_records_are_parsed(tmp_path: Path) -> None:
    price_file = tmp_path / "prices.csv"
    price_file.write_text(
        "date,open,high,low,close,volume,adjusted_close,publication_date\n"
        "2024-01-02,10,12,9,11,100,10.5,2024-01-03\n",
        encoding="utf-8",
    )
    fx_file = tmp_path / "fx.csv"
    fx_file.write_text(
        "base_currency,quote_currency,date,rate\nUSD,JPY,2024-01-02,145.2\n",
        encoding="utf-8",
    )
    provider = CsvHistoricalMarketDataProvider(price_file, fx_file)
    price_rows = provider.fetch_historical_prices(HistoricalPriceRequest(1, "USD"))
    fx_rows = provider.fetch_fx_rates(FxRateRequest())
    assert price_rows[0].row_number == 2
    assert price_rows[0].adjusted_close == Decimal("10.5")
    assert price_rows[0].observation_date == date(2024, 1, 2)
    assert price_rows[0].publication_date == date(2024, 1, 3)
    assert fx_rows[0].base_currency == "USD"
    assert fx_rows[0].rate == Decimal("145.2")


def test_application_provider_contract_is_path_and_csv_independent() -> None:
    signature = inspect.signature(HistoricalPriceProvider.fetch_historical_prices)
    assert "file_path" not in signature.parameters
    assert (
        Path
        not in get_type_hints(HistoricalPriceProvider.fetch_historical_prices).values()
    )


@pytest.mark.parametrize(
    ("content", "method"),
    [
        ("", "price"),
        ("date,open\n2024-01-02,10\n", "price"),
        ("base_currency,rate\nUSD,1\n", "fx"),
    ],
)
def test_csv_provider_rejects_missing_headers(
    tmp_path: Path, content: str, method: str
) -> None:
    file_path = tmp_path / "bad.csv"
    file_path.write_text(content, encoding="utf-8")
    provider = CsvHistoricalMarketDataProvider(file_path, file_path)
    with pytest.raises(CsvFormatError):
        if method == "price":
            provider.fetch_historical_prices(HistoricalPriceRequest(1, "USD"))
        else:
            provider.fetch_fx_rates(FxRateRequest())
