"""Application orchestration for point-in-time Supply & Demand analysis."""

from datetime import UTC, datetime

from cyclescope.application.dto.industry_supply_demand import (
    AnalyzeIndustrySupplyDemandRequest,
    AnalyzeIndustrySupplyDemandResult,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    IndustryInventoryRepository,
    IndustrySignalAggregateRepository,
    IndustrySupplyDemandRepository,
)
from cyclescope.domain.services.industry_supply_demand import (
    calculate_industry_supply_demand,
)


class AnalyzeIndustrySupplyDemand:
    """Read persisted Sprint 17/18 snapshots, calculate, and append a result."""

    def __init__(
        self,
        aggregates: IndustrySignalAggregateRepository,
        inventories: IndustryInventoryRepository,
        snapshots: IndustrySupplyDemandRepository,
    ) -> None:
        self.aggregates = aggregates
        self.inventories = inventories
        self.snapshots = snapshots

    def execute(
        self, request: AnalyzeIndustrySupplyDemandRequest
    ) -> AnalyzeIndustrySupplyDemandResult:
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        cutoff = request.as_of.astimezone(UTC)
        aggregates = tuple(
            self.aggregates.list_by_industry(request.industry_id, as_of=cutoff)
        )
        inventories = tuple(
            self.inventories.list_by_industry(request.industry_id, as_of=cutoff)
        )
        snapshot = calculate_industry_supply_demand(
            aggregates=aggregates,
            inventories=inventories,
            industry_id=request.industry_id,
            sub_industry_id=request.sub_industry_id,
            aggregate_region_id=request.aggregate_region_id,
            aggregate_region_code=request.aggregate_region_code,
            requested_scope=request.requested_scope,
            source_id=request.source_id,
            as_of=cutoff,
            calculated_at=datetime.now(UTC),
            config=request.config,
        )
        return AnalyzeIndustrySupplyDemandResult(self.snapshots.create(snapshot))
