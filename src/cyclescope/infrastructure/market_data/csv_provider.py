"""CSV input adapter for provider-neutral market-data acquisition ports."""

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from cyclescope.application.dto.market_data import (
    FxRateRequest,
    HistoricalPriceRequest,
    RawDailyPriceRecord,
    RawFxRateRecord,
)


class CsvFormatError(ValueError):
    """Raised when a CSV file does not contain its required column headers."""


def _parse_date(value: str | None, field: str, errors: list[str]) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"{field} must use YYYY-MM-DD format.")
        return None


def _parse_decimal(value: str | None, field: str, errors: list[str]) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except InvalidOperation:
        errors.append(f"{field} must be a decimal number.")
        return None
    return parsed


class CsvHistoricalMarketDataProvider:
    """Read configured CSV files and normalize cells into shared market DTOs."""

    def __init__(
        self, price_file_path: Path | None = None, fx_file_path: Path | None = None
    ) -> None:
        self._price_file_path = price_file_path
        self._fx_file_path = fx_file_path

    @staticmethod
    def _read_rows(file_path: Path, required: set[str]) -> list[dict[str, str | None]]:
        with file_path.open("r", encoding="utf-8-sig", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            headers = reader.fieldnames
            if headers is None:
                raise CsvFormatError("CSV file is empty or has no header row.")
            missing_headers = required.difference(headers)
            if missing_headers:
                missing = ", ".join(sorted(missing_headers))
                raise CsvFormatError(f"CSV file is missing required columns: {missing}")
            rows: list[dict[str, str | None]] = []
            for row in reader:
                rows.append(
                    {
                        key: value.strip() if value and value.strip() else None
                        for key in headers
                        if (value := row.get(key)) is not None or key in row
                    }
                )
            return rows

    def fetch_historical_prices(
        self, request: HistoricalPriceRequest
    ) -> tuple[RawDailyPriceRecord, ...]:
        """Parse the configured price CSV and return common daily-price records."""
        if self._price_file_path is None:
            raise ValueError("A price CSV path must be configured for this adapter.")
        rows = self._read_rows(
            self._price_file_path, {"date", "open", "high", "low", "close", "volume"}
        )
        records: list[RawDailyPriceRecord] = []
        for index, row in enumerate(rows, start=2):
            errors: list[str] = []
            volume: int | None = None
            if row.get("volume") is not None:
                try:
                    volume = int(row["volume"] or "")
                except ValueError:
                    errors.append("volume must be a non-negative whole number.")
            record = RawDailyPriceRecord(
                row_number=index,
                observation_date=_parse_date(row.get("date"), "date", errors),
                open=_parse_decimal(row.get("open"), "open", errors),
                high=_parse_decimal(row.get("high"), "high", errors),
                low=_parse_decimal(row.get("low"), "low", errors),
                close=_parse_decimal(row.get("close"), "close", errors),
                volume=volume,
                adjusted_close=_parse_decimal(
                    row.get("adjusted_close"), "adjusted_close", errors
                ),
                publication_date=_parse_date(
                    row.get("publication_date"), "publication_date", errors
                ),
                parsing_errors=tuple(errors),
            )
            if (
                request.start_date is None
                or record.observation_date is None
                or record.observation_date >= request.start_date
            ) and (
                request.end_date is None
                or record.observation_date is None
                or record.observation_date <= request.end_date
            ):
                records.append(record)
        return tuple(records)

    def fetch_fx_rates(self, request: FxRateRequest) -> tuple[RawFxRateRecord, ...]:
        """Parse the configured FX CSV and return common FX records."""
        if self._fx_file_path is None:
            raise ValueError("An FX CSV path must be configured for this adapter.")
        rows = self._read_rows(
            self._fx_file_path,
            {"base_currency", "quote_currency", "date", "rate"},
        )
        records: list[RawFxRateRecord] = []
        for index, row in enumerate(rows, start=2):
            errors: list[str] = []
            record = RawFxRateRecord(
                row_number=index,
                base_currency=row.get("base_currency"),
                quote_currency=row.get("quote_currency"),
                observation_date=_parse_date(row.get("date"), "date", errors),
                rate=_parse_decimal(row.get("rate"), "rate", errors),
                publication_date=_parse_date(
                    row.get("publication_date"), "publication_date", errors
                ),
                parsing_errors=tuple(errors),
            )
            pair_matches = (
                request.base_currency is None
                or request.base_currency.upper() == (record.base_currency or "").upper()
            ) and (
                request.quote_currency is None
                or request.quote_currency.upper()
                == (record.quote_currency or "").upper()
            )
            in_range = (
                request.start_date is None
                or record.observation_date is None
                or record.observation_date >= request.start_date
            ) and (
                request.end_date is None
                or record.observation_date is None
                or record.observation_date <= request.end_date
            )
            if pair_matches and in_range:
                records.append(record)
        return tuple(records)
