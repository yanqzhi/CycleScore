"""Region registration and relationship-based hierarchy queries."""

from cyclescope.application.dto.region import (
    CreatedRegionResult,
    CreateRegionRelationshipRequest,
    CreateRegionRequest,
    GetRegionAncestorPathsResult,
    GetRegionDescendantsResult,
    GetRegionHierarchyRequest,
    GetRegionParentsResult,
    GetRegionRequest,
    GetRegionResult,
    IsRegionDescendantRequest,
    ValidateRegionHierarchyResult,
)
from cyclescope.domain.entities.region import Region, RegionRelationship
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    RegionRelationshipRepository,
    RegionRepository,
)
from cyclescope.domain.services.region_hierarchy import (
    ancestor_paths,
    descendants,
    is_descendant,
    validate_relationship,
)


class RegisterRegion:
    def __init__(self, regions: RegionRepository) -> None:
        self.regions = regions

    def execute(self, request: CreateRegionRequest) -> CreatedRegionResult:
        if self.regions.get_by_code(request.region_code) is not None:
            raise DomainValidationError("Region code already exists.")
        return CreatedRegionResult(
            region=self.regions.create(
                Region(
                    region_code=request.region_code,
                    name=request.name,
                    region_type=request.region_type,
                    country_code=request.country_code,
                    is_active=request.is_active,
                )
            )
        )


class RegisterRegionRelationship:
    def __init__(
        self,
        regions: RegionRepository,
        relationships: RegionRelationshipRepository,
    ) -> None:
        self.regions = regions
        self.relationships = relationships

    def execute(self, request: CreateRegionRelationshipRequest) -> CreatedRegionResult:
        relationship = RegionRelationship(
            parent_region_id=request.parent_region_id,
            child_region_id=request.child_region_id,
        )
        if self.relationships.exists(relationship):
            raise DomainValidationError("Region relationship already exists.")
        region_list = self.regions.list()
        region_map = {item.id or 0: item for item in region_list}
        validate_relationship(
            region_map, tuple(self.relationships.list_all()), relationship
        )
        return CreatedRegionResult(relationship=self.relationships.create(relationship))


class GetRegionByCode:
    def __init__(self, regions: RegionRepository) -> None:
        self.regions = regions

    def execute(self, request: GetRegionRequest) -> GetRegionResult:
        region = self.regions.get_by_code(request.region_code)
        if region is None:
            raise DomainValidationError("Unknown region code.")
        return GetRegionResult(region)


class GetRegionParents:
    def __init__(
        self,
        regions: RegionRepository,
        relationships: RegionRelationshipRepository,
    ) -> None:
        self.regions = regions
        self.relationships = relationships

    def execute(self, request: GetRegionHierarchyRequest) -> GetRegionParentsResult:
        region = _region_by_code(self.regions, request.region_code)
        parents = tuple(
            sorted(
                (
                    parent
                    for edge in self.relationships.list_by_child(region.id or 0)
                    if (parent := self.regions.get_by_id(edge.parent_region_id))
                    is not None
                ),
                key=lambda item: item.region_code,
            )
        )
        return GetRegionParentsResult(region, parents)


class GetRegionDescendants:
    def __init__(
        self,
        regions: RegionRepository,
        relationships: RegionRelationshipRepository,
    ) -> None:
        self.regions = regions
        self.relationships = relationships

    def execute(self, request: GetRegionHierarchyRequest) -> GetRegionDescendantsResult:
        region = _region_by_code(self.regions, request.region_code)
        region_map, edges = _validated_graph(self.regions, self.relationships)
        return GetRegionDescendantsResult(
            region, descendants(region.id or 0, region_map, edges)
        )


class GetRegionAncestorPaths:
    def __init__(
        self,
        regions: RegionRepository,
        relationships: RegionRelationshipRepository,
    ) -> None:
        self.regions = regions
        self.relationships = relationships

    def execute(
        self, request: GetRegionHierarchyRequest
    ) -> GetRegionAncestorPathsResult:
        region = _region_by_code(self.regions, request.region_code)
        region_map, edges = _validated_graph(self.regions, self.relationships)
        return GetRegionAncestorPathsResult(
            region, ancestor_paths(region.id or 0, region_map, edges)
        )


class IsRegionDescendant:
    def __init__(
        self,
        regions: RegionRepository,
        relationships: RegionRelationshipRepository,
    ) -> None:
        self.regions = regions
        self.relationships = relationships

    def execute(self, request: IsRegionDescendantRequest) -> bool:
        region = _region_by_code(self.regions, request.region_code)
        ancestor = _region_by_code(self.regions, request.ancestor_region_code)
        region_map, edges = _validated_graph(self.regions, self.relationships)
        return is_descendant(region.id or 0, ancestor.id or 0, region_map, edges)


class ValidateRegionHierarchy:
    def __init__(
        self,
        regions: RegionRepository,
        relationships: RegionRelationshipRepository,
    ) -> None:
        self.regions = regions
        self.relationships = relationships

    def execute(self) -> ValidateRegionHierarchyResult:
        region_map, edges = _validated_graph(self.regions, self.relationships)
        return ValidateRegionHierarchyResult(True, len(region_map), len(edges))


def _region_by_code(regions: RegionRepository, region_code: str) -> Region:
    region = regions.get_by_code(region_code)
    if region is None:
        raise DomainValidationError("Unknown region code.")
    return region


def _validated_graph(
    regions: RegionRepository, relationships: RegionRelationshipRepository
) -> tuple[dict[int, Region], tuple[RegionRelationship, ...]]:
    region_map = {item.id or 0: item for item in regions.list()}
    edges = tuple(relationships.list_all())
    validate_relationship(region_map, edges)
    return region_map, edges
