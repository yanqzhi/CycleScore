"""Application orchestration for PIT industry inventory analysis."""

from datetime import UTC, datetime

from cyclescope.application.dto.industry_inventory import (
    AnalyzeIndustryInventoryRequest,
    AnalyzeIndustryInventoryResult,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    IndustryInventoryRepository,
    IndustrySignalAggregateRepository,
)
from cyclescope.domain.services.industry_inventory import calculate_industry_inventory


class AnalyzeIndustryInventory:
    """Consume only persisted PIT aggregates and append an immutable analysis."""

    def __init__(
        self,
        aggregates: IndustrySignalAggregateRepository,
        snapshots: IndustryInventoryRepository,
    ) -> None:
        self.aggregates = aggregates
        self.snapshots = snapshots

    def execute(
        self, request: AnalyzeIndustryInventoryRequest
    ) -> AnalyzeIndustryInventoryResult:
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        cutoff = request.as_of.astimezone(UTC)
        history = tuple(
            self.aggregates.list_by_industry(request.industry_id, as_of=cutoff)
        )
        snapshot = calculate_industry_inventory(
            aggregates=history,
            industry_id=request.industry_id,
            sub_industry_id=request.sub_industry_id,
            aggregate_region_code=request.aggregate_region_code,
            requested_scope=request.requested_scope,
            source_id=request.source_id,
            as_of=cutoff,
            calculated_at=datetime.now(UTC),
            config=request.config,
        )
        return AnalyzeIndustryInventoryResult(self.snapshots.create(snapshot))
