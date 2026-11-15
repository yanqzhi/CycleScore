"""Provider-neutral commands and queries for industry signals."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from cyclescope.domain.entities.industry_signal import (
    IndustrySignalObservation,
    IndustrySignalType,
    IndustrySignalUnit,
)


@dataclass(frozen=True, slots=True)
class IndustrySignalInput:
    industry_id: int
    source_id: int
    signal_type: IndustrySignalType
    region_code: str
    unit_code: IndustrySignalUnit
    value: Decimal | None
    publication_date: date
    publication_datetime: datetime | None
    available_at: datetime
    collected_at: datetime
    revision_number: int
    sub_industry_id: int | None = None
    currency_code: str | None = None
    observation_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    source_reference: str | None = None
    missing_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ImportIndustrySignalsRequest:
    observations: tuple[IndustrySignalInput, ...]


@dataclass(frozen=True, slots=True)
class ImportIndustrySignalsResult:
    observations: tuple[IndustrySignalObservation, ...]


@dataclass(frozen=True, slots=True)
class GetIndustrySignalsRequest:
    industry_id: int
    as_of: datetime
    signal_type: IndustrySignalType | None = None
    sub_industry_id: int | None = None
    region_code: str | None = None
    source_id: int | None = None


@dataclass(frozen=True, slots=True)
class GetIndustrySignalsResult:
    observations: tuple[IndustrySignalObservation, ...]
