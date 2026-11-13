"""Typed application inputs, provider records, and import summaries."""

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from cyclescope.domain.entities.daily_price import DailyPrice
from cyclescope.domain.entities.fx_rate import FxRate


@dataclass(frozen=True, slots=True)
class CsvPriceRecord:
    """Unnormalized values read from one CSV price row."""

    row_number: int
    observation_date: str | None
    open: str | None
    high: str | None
    low: str | None
    close: str | None
    volume: str | None
    adjusted_close: str | None = None
    publication_date: str | None = None


@dataclass(frozen=True, slots=True)
class CsvFxRateRecord:
    """Unnormalized values read from one CSV FX row."""

    row_number: int
    base_currency: str | None
    quote_currency: str | None
    observation_date: str | None
    rate: str | None
    publication_date: str | None = None


@dataclass(frozen=True, slots=True)
class ImportHistoricalPricesInput:
    """CSV and provenance metadata for importing one security's prices."""

    file_path: Path
    security_id: int
    currency: str
    source_id: int
    available_at: datetime
    collected_at: datetime
    revision_number: int = 1


@dataclass(frozen=True, slots=True)
class ImportFxRatesInput:
    """CSV and provenance metadata for importing FX revisions."""

    file_path: Path
    source_id: int
    available_at: datetime
    collected_at: datetime
    revision_number: int = 1


@dataclass(frozen=True, slots=True)
class GetHistoricalPricesInput:
    """Price query with an explicit point-in-time cutoff."""

    security_id: int
    start_date: date
    end_date: date
    as_of: datetime
    source_id: int | None = None


@dataclass(frozen=True, slots=True)
class GetHistoricalFxRatesInput:
    """FX query with an explicit point-in-time cutoff."""

    base_currency: str
    quote_currency: str
    start_date: date
    end_date: date
    as_of: datetime
    source_id: int | None = None


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A row-level import rejection with its source row and reason."""

    row_number: int
    message: str


@dataclass(frozen=True, slots=True)
class PriceImportSummary:
    """Price-specific import response."""

    total_records: int
    imported_records: int
    skipped_duplicates: int
    rejected_records: int
    validation_errors: tuple[ValidationIssue, ...]
    imported_observations: tuple[DailyPrice, ...] = ()


@dataclass(frozen=True, slots=True)
class FxImportSummary:
    """FX-specific import response."""

    total_records: int
    imported_records: int
    skipped_duplicates: int
    rejected_records: int
    validation_errors: tuple[ValidationIssue, ...]
    imported_observations: tuple[FxRate, ...] = ()
