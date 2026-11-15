"""Geographic and market region nodes and explicit containment edges."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from cyclescope.domain.exceptions import DomainValidationError


def _aware_utc(name: str, value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


class RegionType(StrEnum):
    GLOBAL = "GLOBAL"
    CONTINENT = "CONTINENT"
    COUNTRY = "COUNTRY"
    ECONOMIC_REGION = "ECONOMIC_REGION"
    MARKET_REGION = "MARKET_REGION"
    UNSPECIFIED = "UNSPECIFIED"


class RegionRelationshipType(StrEnum):
    CONTAINS = "CONTAINS"


_ALLOWED_CHILD_TYPES: dict[RegionType, frozenset[RegionType]] = {
    RegionType.GLOBAL: frozenset(
        {
            RegionType.CONTINENT,
            RegionType.COUNTRY,
            RegionType.ECONOMIC_REGION,
            RegionType.MARKET_REGION,
        }
    ),
    RegionType.CONTINENT: frozenset(
        {RegionType.COUNTRY, RegionType.ECONOMIC_REGION, RegionType.MARKET_REGION}
    ),
    RegionType.COUNTRY: frozenset(
        {RegionType.ECONOMIC_REGION, RegionType.MARKET_REGION}
    ),
    RegionType.ECONOMIC_REGION: frozenset({RegionType.MARKET_REGION}),
    RegionType.MARKET_REGION: frozenset(),
    RegionType.UNSPECIFIED: frozenset(),
}


def validate_region_parent_type(parent: RegionType, child: RegionType) -> None:
    """Reject region edges that contradict the declared region types."""
    if child not in _ALLOWED_CHILD_TYPES[parent]:
        raise DomainValidationError(
            f"A {parent.value} region cannot contain a {child.value} region."
        )


@dataclass(frozen=True, slots=True)
class Region:
    region_code: str
    name: str
    region_type: RegionType
    id: int | None = None
    country_code: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if (
            not self.region_code
            or self.region_code != self.region_code.strip()
            or len(self.region_code) > 64
            or not self.region_code.isascii()
            or not (self.region_code[0].isalnum() and self.region_code[0].isascii())
            or not all(
                char.isupper() or char.isdigit() or char in "_.:-"
                for char in self.region_code
            )
        ):
            raise DomainValidationError("region_code must be a normalized code.")
        if not self.name.strip():
            raise DomainValidationError("Region name is required.")
        if not isinstance(self.region_type, RegionType):
            raise DomainValidationError("region_type is invalid.")
        if self.country_code is not None and (
            len(self.country_code) != 2
            or not self.country_code.isascii()
            or not self.country_code.isalpha()
            or not self.country_code.isupper()
        ):
            raise DomainValidationError("country_code must be two uppercase letters.")
        object.__setattr__(
            self, "created_at", _aware_utc("created_at", self.created_at)
        )
        object.__setattr__(
            self, "updated_at", _aware_utc("updated_at", self.updated_at)
        )


@dataclass(frozen=True, slots=True)
class RegionRelationship:
    parent_region_id: int
    child_region_id: int
    relationship_type: RegionRelationshipType = RegionRelationshipType.CONTAINS
    id: int | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.parent_region_id < 1 or self.child_region_id < 1:
            raise DomainValidationError("Region relationship IDs must be positive.")
        if self.parent_region_id == self.child_region_id:
            raise DomainValidationError("A region cannot contain itself.")
        if not isinstance(self.relationship_type, RegionRelationshipType):
            raise DomainValidationError("relationship_type is invalid.")
        object.__setattr__(
            self, "created_at", _aware_utc("created_at", self.created_at)
        )
