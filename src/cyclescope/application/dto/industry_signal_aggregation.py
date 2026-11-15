"""Commands and results for point-in-time industry signal aggregation."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from cyclescope.domain.entities.industry_signal import (
    IndustrySignalType,
    IndustrySignalUnit,
)
from cyclescope.domain.entities.industry_signal_aggregate import (
    IndustrySignalAggregateSnapshot,
)


@dataclass(frozen=True, slots=True)
class AggregateIndustrySignalsRequest:
    industry_id: int
    signal_type: IndustrySignalType
    aggregate_region_code: str
    constituent_region_codes: tuple[str, ...]
    policy_code: str
    policy_version: int
    unit_code: IndustrySignalUnit
    as_of: datetime
    sub_industry_id: int | None = None
    source_id: int | None = None
    currency_code: str | None = None
    observation_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    expected_contributor_count: int | None = None
    minimum_coverage: Decimal | None = None


@dataclass(frozen=True, slots=True)
class AggregateIndustrySignalsResult:
    snapshot: IndustrySignalAggregateSnapshot


@dataclass(frozen=True, slots=True)
class GetIndustrySignalAggregateRequest:
    aggregate_id: int


@dataclass(frozen=True, slots=True)
class GetIndustrySignalAggregateResult:
    snapshot: IndustrySignalAggregateSnapshot


@dataclass(frozen=True, slots=True)
class GetIndustrySignalAggregatesRequest:
    industry_id: int
    signal_type: IndustrySignalType | None = None
    as_of: datetime | None = None


@dataclass(frozen=True, slots=True)
class GetIndustrySignalAggregatesResult:
    snapshots: tuple[IndustrySignalAggregateSnapshot, ...]
