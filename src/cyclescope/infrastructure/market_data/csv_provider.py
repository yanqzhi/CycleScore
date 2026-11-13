"""CSV-backed historical price and FX provider."""

import csv
from pathlib import Path

from cyclescope.application.dto.market_data import CsvFxRateRecord, CsvPriceRecord


class CsvFormatError(ValueError):
    """Raised when a CSV file does not contain its required column headers."""


class CsvHistoricalMarketDataProvider:
    """Read documented CSV columns without performing business validation."""

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
                normalized: dict[str, str | None] = {}
                for key in headers:
                    value = row.get(key)
                    normalized[key] = (
                        value.strip() if value is not None and value.strip() else None
                    )
                rows.append(normalized)
            return rows

    def read_prices(self, file_path: Path) -> tuple[CsvPriceRecord, ...]:
        """Read ``date,open,high,low,close,volume`` CSV rows."""
        rows = self._read_rows(
            file_path, {"date", "open", "high", "low", "close", "volume"}
        )
        return tuple(
            CsvPriceRecord(
                row_number=index,
                observation_date=row.get("date"),
                open=row.get("open"),
                high=row.get("high"),
                low=row.get("low"),
                close=row.get("close"),
                volume=row.get("volume"),
                adjusted_close=row.get("adjusted_close"),
                publication_date=row.get("publication_date"),
            )
            for index, row in enumerate(rows, start=2)
        )

    def read_fx_rates(self, file_path: Path) -> tuple[CsvFxRateRecord, ...]:
        """Read ``base_currency,quote_currency,date,rate`` CSV rows."""
        rows = self._read_rows(
            file_path, {"base_currency", "quote_currency", "date", "rate"}
        )
        return tuple(
            CsvFxRateRecord(
                row_number=index,
                base_currency=row.get("base_currency"),
                quote_currency=row.get("quote_currency"),
                observation_date=row.get("date"),
                rate=row.get("rate"),
                publication_date=row.get("publication_date"),
            )
            for index, row in enumerate(rows, start=2)
        )
