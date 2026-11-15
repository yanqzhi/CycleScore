"""Commands for industry inventory cycle analysis."""

from dataclasses import dataclass
from datetime import datetime

from cyclescope.domain.entities.industry_inventory import (
    IndustryInventoryConfig,
    IndustryInventorySnapshot,
)


@dataclass(frozen=True, slots=True)
class AnalyzeIndustryInventoryRequest:
    industry_id: int
    aggregate_region_code: str
    requested_scope: tuple[tuple[int, str], ...]
    as_of: datetime
    config: IndustryInventoryConfig
    sub_industry_id: int | None = None
    source_id: int | None = None


@dataclass(frozen=True, slots=True)
class AnalyzeIndustryInventoryResult:
    snapshot: IndustryInventorySnapshot
