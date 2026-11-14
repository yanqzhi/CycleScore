"""CSV market-data parsing shared by legacy and generic Infrastructure adapters."""

import csv
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path

from cyclescope.application.dto.market_data import (
    FxRateRequest,
    HistoricalPriceRequest,
    RawDailyPriceRecord,
    RawFxRateRecord,
)


class CsvFormatError(ValueError):
    """Raised when a CSV payload has malformed or missing headers."""


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
        return Decimal(value)
    except InvalidOperation:
        errors.append(f"{field} must be a decimal number.")
        return None


def _read_rows(
    payload: bytes, required: set[str]
) -> list[tuple[int, dict[str, str | None], tuple[str, ...]]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvFormatError("CSV payload must be UTF-8 encoded.") from exc
    reader = csv.DictReader(StringIO(text, newline=""))
    raw_headers = reader.fieldnames
    if raw_headers is None:
        raise CsvFormatError("CSV file is empty or has no header row.")
    headers = [header.strip() if header is not None else "" for header in raw_headers]
    if any(not header for header in headers):
        raise CsvFormatError("CSV headers must not be empty.")
    if len(headers) != len(set(headers)):
        raise CsvFormatError("CSV headers must be unique.")
    reader.fieldnames = headers
    missing_headers = required.difference(headers)
    if missing_headers:
        missing = ", ".join(sorted(missing_headers))
        raise CsvFormatError(f"CSV file is missing required columns: {missing}")
    rows: list[tuple[int, dict[str, str | None], tuple[str, ...]]] = []
    for row in reader:
        errors: list[str] = []
        if None in row and any(value and value.strip() for value in row[None] or []):
            errors.append("row contains more values than the CSV header.")
        values = {
            key: value.strip() if value and value.strip() else None
            for key, value in row.items()
            if key is not None
        }
        rows.append((reader.line_num, values, tuple(errors)))
    return rows


def parse_daily_price_csv(payload: bytes) -> tuple[RawDailyPriceRecord, ...]:
    """Parse price CSV bytes into common row DTOs without persistence."""
    rows = _read_rows(payload, {"date", "open", "high", "low", "close", "volume"})
    records: list[RawDailyPriceRecord] = []
    for row_number, row, row_errors in rows:
        errors = list(row_errors)
        volume: int | None = None
        if row.get("volume") is not None:
            try:
                volume = int(row["volume"] or "")
            except ValueError:
                errors.append("volume must be a non-negative whole number.")
        records.append(
            RawDailyPriceRecord(
                row_number=row_number,
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
        )
    return tuple(records)


def parse_fx_rate_csv(payload: bytes) -> tuple[RawFxRateRecord, ...]:
    """Parse FX CSV bytes into common row DTOs without persistence."""
    rows = _read_rows(payload, {"base_currency", "quote_currency", "date", "rate"})
    records: list[RawFxRateRecord] = []
    for row_number, row, row_errors in rows:
        errors = list(row_errors)
        records.append(
            RawFxRateRecord(
                row_number=row_number,
                base_currency=row.get("base_currency"),
                quote_currency=row.get("quote_currency"),
                observation_date=_parse_date(row.get("date"), "date", errors),
                rate=_parse_decimal(row.get("rate"), "rate", errors),
                publication_date=_parse_date(
                    row.get("publication_date"), "publication_date", errors
                ),
                parsing_errors=tuple(errors),
            )
        )
    return tuple(records)


class CsvHistoricalMarketDataProvider:
    """Read configured CSV files into the existing market-data DTO contracts."""

    def __init__(
        self, price_file_path: Path | None = None, fx_file_path: Path | None = None
    ) -> None:
        self._price_file_path = price_file_path
        self._fx_file_path = fx_file_path

    def fetch_historical_prices(
        self, request: HistoricalPriceRequest
    ) -> tuple[RawDailyPriceRecord, ...]:
        if self._price_file_path is None:
            raise ValueError("A price CSV path must be configured for this adapter.")
        records = parse_daily_price_csv(self._price_file_path.read_bytes())
        return tuple(
            row
            for row in records
            if (
                request.start_date is None
                or row.observation_date is None
                or row.observation_date >= request.start_date
            )
            and (
                request.end_date is None
                or row.observation_date is None
                or row.observation_date <= request.end_date
            )
        )

    def fetch_fx_rates(self, request: FxRateRequest) -> tuple[RawFxRateRecord, ...]:
        if self._fx_file_path is None:
            raise ValueError("An FX CSV path must be configured for this adapter.")
        records = parse_fx_rate_csv(self._fx_file_path.read_bytes())
        return tuple(
            row
            for row in records
            if (
                request.base_currency is None
                or request.base_currency.upper() == (row.base_currency or "").upper()
            )
            and (
                request.quote_currency is None
                or request.quote_currency.upper() == (row.quote_currency or "").upper()
            )
            and (
                request.start_date is None
                or row.observation_date is None
                or row.observation_date >= request.start_date
            )
            and (
                request.end_date is None
                or row.observation_date is None
                or row.observation_date <= request.end_date
            )
        )
