"""Region master commands and deterministic hierarchy query results."""

from dataclasses import dataclass

from cyclescope.domain.entities.region import (
    Region,
    RegionRelationship,
    RegionType,
)


@dataclass(frozen=True, slots=True)
class CreateRegionRequest:
    region_code: str
    name: str
    region_type: RegionType
    country_code: str | None = None
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class CreateRegionRelationshipRequest:
    parent_region_id: int
    child_region_id: int


@dataclass(frozen=True, slots=True)
class GetRegionRequest:
    region_code: str


@dataclass(frozen=True, slots=True)
class GetRegionHierarchyRequest:
    region_code: str


@dataclass(frozen=True, slots=True)
class GetRegionResult:
    region: Region


@dataclass(frozen=True, slots=True)
class GetRegionParentsResult:
    region: Region
    parents: tuple[Region, ...]


@dataclass(frozen=True, slots=True)
class GetRegionDescendantsResult:
    region: Region
    descendants: tuple[Region, ...]


@dataclass(frozen=True, slots=True)
class GetRegionAncestorPathsResult:
    region: Region
    paths: tuple[tuple[Region, ...], ...]


@dataclass(frozen=True, slots=True)
class IsRegionDescendantRequest:
    region_code: str
    ancestor_region_code: str


@dataclass(frozen=True, slots=True)
class ValidateRegionHierarchyResult:
    is_valid: bool
    regions_checked: int
    relationships_checked: int


@dataclass(frozen=True, slots=True)
class CreatedRegionResult:
    region: Region | None = None
    relationship: RegionRelationship | None = None
