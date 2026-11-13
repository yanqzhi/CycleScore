"""Provider-independent market-data requests and transfer objects."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from cyclescope.domain.entities.daily_price import DailyPrice
from cyclescope.domain.entities.fx_rate import FxRate


@dataclass(frozen=True, slots=True)
class HistoricalPriceRequest:
    """Request daily prices for a security and optional date range."""

    security_id: int
    currency: str
    start_date: date | None = None
    end_date: date | None = None


@dataclass(frozen=True, slots=True)
class FxRateRequest:
    """Request observations for an FX pair and optional date range."""

    base_currency: str | None = None
    quote_currency: str | None = None
    start_date: date | None = None
    end_date: date | None = None


@dataclass(frozen=True, slots=True)
class RawDailyPriceRecord:
    """Normalized provider-neutral values from one daily price observation."""

    row_number: int
    observation_date: date | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal | None
    volume: int | None
    adjusted_close: Decimal | None = None
    publication_date: date | None = None
    parsing_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RawFxRateRecord:
    """Normalized provider-neutral values from one FX observation."""

    row_number: int
    base_currency: str | None
    quote_currency: str | None
    observation_date: date | None
    rate: Decimal | None
    publication_date: date | None = None
    parsing_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ImportHistoricalPricesInput:
    """Price import request and provenance metadata."""

    request: HistoricalPriceRequest
    source_id: int
    available_at: datetime
    collected_at: datetime
    revision_number: int = 1


@dataclass(frozen=True, slots=True)
class ImportFxRatesInput:
    """FX import request and provenance metadata."""

    request: FxRateRequest
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
