"""CSV market-data provider parsing tests."""

from pathlib import Path

import pytest

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
    provider = CsvHistoricalMarketDataProvider()
    price_rows = provider.read_prices(price_file)
    fx_rows = provider.read_fx_rates(fx_file)
    assert price_rows[0].row_number == 2
    assert price_rows[0].adjusted_close == "10.5"
    assert price_rows[0].publication_date == "2024-01-03"
    assert fx_rows[0].base_currency == "USD"
    assert fx_rows[0].rate == "145.2"


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
    provider = CsvHistoricalMarketDataProvider()
    with pytest.raises(CsvFormatError):
        if method == "price":
            provider.read_prices(file_path)
        else:
            provider.read_fx_rates(file_path)
