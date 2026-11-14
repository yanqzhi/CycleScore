"""Input and result contracts for market-data assessment and revision review."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from cyclescope.domain.entities.data_quality import DataAnomaly, DataQualityReport
from cyclescope.domain.value_objects.data_quality import DatasetType


@dataclass(frozen=True, slots=True)
class PriceQualityRequest:
    security_id: int
    start_date: date
    end_date: date
    source_id: int | None
    as_of: datetime
    exchange_id: int | None


@dataclass(frozen=True, slots=True)
class FxQualityRequest:
    base_currency: str
    quote_currency: str
    start_date: date
    end_date: date
    source_id: int | None
    as_of: datetime


@dataclass(frozen=True, slots=True)
class QualityAssessmentResult:
    report: DataQualityReport
    anomalies: tuple[DataAnomaly, ...]


@dataclass(frozen=True, slots=True)
class RevisionComparison:
    dataset_type: DatasetType
    observation_date: date
    source_id: int
    earlier_revision: int
    later_revision: int
    changes: tuple[
        tuple[
            str,
            Decimal | int | str | date | datetime | None,
            Decimal | int | str | date | datetime | None,
        ],
        ...,
    ]
    earlier_available_at: datetime
    later_available_at: datetime
    earlier_collected_at: datetime
    later_collected_at: datetime
