"""Point-in-time orchestration for industry signal aggregate snapshots."""

from datetime import UTC, datetime

from cyclescope.application.dto.industry_signal import GetIndustrySignalsRequest
from cyclescope.application.dto.industry_signal_aggregation import (
    AggregateIndustrySignalsRequest,
    AggregateIndustrySignalsResult,
    GetIndustrySignalAggregateRequest,
    GetIndustrySignalAggregateResult,
    GetIndustrySignalAggregatesRequest,
    GetIndustrySignalAggregatesResult,
)
from cyclescope.application.use_cases.industry_signals import GetIndustrySignals
from cyclescope.domain.entities.industry_signal import IndustrySignalType
from cyclescope.domain.entities.industry_signal_aggregate import (
    AggregationOperation,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    IndustrySignalAggregateRepository,
    RegionRelationshipRepository,
    RegionRepository,
)
from cyclescope.domain.services.industry_signal_aggregation import (
    calculate_industry_signal_aggregate,
    resolve_aggregation_policy,
    validate_aggregation_region_scope,
)
from cyclescope.domain.services.region_hierarchy import validate_relationship


class AggregateIndustrySignals:
    """Select PIT observations, validate scope, calculate, and append a snapshot."""

    def __init__(
        self,
        signal_query: GetIndustrySignals,
        aggregates: IndustrySignalAggregateRepository,
        regions: RegionRepository,
        relationships: RegionRelationshipRepository,
    ) -> None:
        self.signal_query = signal_query
        self.aggregates = aggregates
        self.regions = regions
        self.relationships = relationships

    def execute(
        self, request: AggregateIndustrySignalsRequest
    ) -> AggregateIndustrySignalsResult:
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        as_of = request.as_of.astimezone(UTC)
        policy = resolve_aggregation_policy(
            request.policy_code,
            request.policy_version,
            request.signal_type,
            request.minimum_coverage,
        )
        region_items = self.regions.list()
        region_by_code = {item.region_code: item for item in region_items}
        aggregate_scope = region_by_code.get(request.aggregate_region_code)
        if aggregate_scope is None:
            raise DomainValidationError("Unknown aggregate region code.")
        try:
            constituents = tuple(
                region_by_code[code] for code in request.constituent_region_codes
            )
        except KeyError as exc:
            raise DomainValidationError("Unknown constituent region code.") from exc
        region_by_id = {region.id or 0: region for region in region_items}
        edges = tuple(self.relationships.list_all())
        validate_relationship(region_by_id, edges)
        validate_aggregation_region_scope(aggregate_scope, constituents, edges)

        measures = tuple(
            observation
            for region_code in request.constituent_region_codes
            for observation in self.signal_query.execute(
                GetIndustrySignalsRequest(
                    industry_id=request.industry_id,
                    as_of=as_of,
                    signal_type=request.signal_type,
                    sub_industry_id=request.sub_industry_id,
                    region_code=region_code,
                    source_id=request.source_id,
                )
            ).observations
        )
        capacities = (
            tuple(
                observation
                for region_code in request.constituent_region_codes
                for observation in self.signal_query.execute(
                    GetIndustrySignalsRequest(
                        industry_id=request.industry_id,
                        as_of=as_of,
                        signal_type=IndustrySignalType.CAPACITY,
                        sub_industry_id=request.sub_industry_id,
                        region_code=region_code,
                        source_id=request.source_id,
                    )
                ).observations
            )
            if policy.operation is AggregationOperation.CAPACITY_WEIGHTED_AVERAGE
            else ()
        )
        snapshot = calculate_industry_signal_aggregate(
            policy=policy,
            observations=measures,
            capacity_observations=capacities,
            industry_id=request.industry_id,
            sub_industry_id=request.sub_industry_id,
            aggregate_region_code=request.aggregate_region_code,
            constituent_region_codes=request.constituent_region_codes,
            unit_code=request.unit_code,
            currency_code=request.currency_code,
            observation_date=request.observation_date,
            period_start=request.period_start,
            period_end=request.period_end,
            as_of=as_of,
            calculated_at=datetime.now(UTC),
            expected_contributor_count=request.expected_contributor_count,
            requested_source_id=request.source_id,
            aggregate_region_id=aggregate_scope.id or 0,
            constituent_regions=constituents,
        )
        return AggregateIndustrySignalsResult(self.aggregates.create(snapshot))


class GetIndustrySignalAggregate:
    """Retrieve one aggregate snapshot with the stored contributor audit."""

    def __init__(self, aggregates: IndustrySignalAggregateRepository) -> None:
        self.aggregates = aggregates

    def execute(
        self, request: GetIndustrySignalAggregateRequest
    ) -> GetIndustrySignalAggregateResult:
        result = self.aggregates.get_by_id(request.aggregate_id)
        if result is None:
            raise DomainValidationError("Unknown industry signal aggregate.")
        return GetIndustrySignalAggregateResult(result)


class GetIndustrySignalAggregates:
    """List immutable aggregate history with optional PIT display cutoff."""

    def __init__(self, aggregates: IndustrySignalAggregateRepository) -> None:
        self.aggregates = aggregates

    def execute(
        self, request: GetIndustrySignalAggregatesRequest
    ) -> GetIndustrySignalAggregatesResult:
        if request.as_of is not None and (
            request.as_of.tzinfo is None or request.as_of.utcoffset() is None
        ):
            raise DomainValidationError("as_of must be timezone-aware.")
        cutoff = request.as_of.astimezone(UTC) if request.as_of else None
        return GetIndustrySignalAggregatesResult(
            tuple(
                self.aggregates.list_by_industry(
                    request.industry_id,
                    signal_type=request.signal_type,
                    as_of=cutoff,
                )
            )
        )
