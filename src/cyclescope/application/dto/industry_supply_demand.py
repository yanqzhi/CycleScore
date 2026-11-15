"""Typed application requests/results for Industry Supply & Demand."""

from dataclasses import dataclass
from datetime import datetime

from cyclescope.domain.entities.industry_supply_demand import (
    IndustrySupplyDemandConfig,
    IndustrySupplyDemandSnapshot,
)


@dataclass(frozen=True, slots=True)
class AnalyzeIndustrySupplyDemandRequest:
    industry_id: int
    aggregate_region_code: str
    requested_scope: tuple[tuple[int, str], ...]
    as_of: datetime
    config: IndustrySupplyDemandConfig
    aggregate_region_id: int | None = None
    sub_industry_id: int | None = None
    source_id: int | None = None


@dataclass(frozen=True, slots=True)
class AnalyzeIndustrySupplyDemandResult:
    snapshot: IndustrySupplyDemandSnapshot
