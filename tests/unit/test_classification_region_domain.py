"""Domain validation and deterministic region graph tests."""

from datetime import date
from decimal import Decimal

import pytest

from cyclescope.domain.entities.classification import (
    ClassificationScheme,
    ClassificationVersion,
    IndustryClassificationMapping,
    MappingMethod,
)
from cyclescope.domain.entities.region import (
    Region,
    RegionRelationship,
    RegionType,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.services.region_hierarchy import (
    ancestor_paths,
    descendants,
    is_descendant,
    validate_relationship,
)


def test_classification_entities_validate_effective_ranges_and_confidence() -> None:
    with pytest.raises(DomainValidationError, match="date range"):
        ClassificationVersion(1, "V1", date(2025, 1, 2), effective_to=date(2025, 1, 1))
    with pytest.raises(DomainValidationError, match="confidence"):
        IndustryClassificationMapping(
            1,
            "EXT-1",
            "External",
            1,
            date(2025, 1, 1),
            MappingMethod.MANUAL,
            confidence=Decimal("1.01"),
        )
    with pytest.raises(DomainValidationError, match="normalized uppercase"):
        ClassificationScheme("bad code", "Scheme", "Publisher")


def test_region_dag_supports_multiple_parents_and_deterministic_paths() -> None:
    global_region = Region("GLOBAL", "Global", RegionType.GLOBAL, id=1)
    asia = Region("ASIA", "Asia", RegionType.CONTINENT, id=2)
    europe = Region("EUROPE", "Europe", RegionType.CONTINENT, id=3)
    market = Region("EUR_MARKET", "Euro market", RegionType.MARKET_REGION, id=4)
    regions = {item.id or 0: item for item in (global_region, asia, europe, market)}
    edges = (
        RegionRelationship(1, 2),
        RegionRelationship(1, 3),
        RegionRelationship(2, 4),
        RegionRelationship(3, 4),
    )

    validate_relationship(regions, edges)

    paths = ancestor_paths(4, regions, edges)
    assert [[item.region_code for item in path] for path in paths] == [
        ["GLOBAL", "ASIA"],
        ["GLOBAL", "EUROPE"],
    ]
    assert [item.region_code for item in descendants(1, regions, edges)] == [
        "ASIA",
        "EUROPE",
        "EUR_MARKET",
    ]
    assert is_descendant(4, 1, regions, edges)
    assert ancestor_paths(1, regions, edges) == ()


@pytest.mark.parametrize(
    ("parent_id", "child_id", "message"),
    [
        (3, 1, "cannot contain"),
    ],
)
def test_region_rejects_incompatible_edges(parent_id, child_id, message) -> None:
    regions = {
        1: Region("GLOBAL", "Global", RegionType.GLOBAL, id=1),
        2: Region("ASIA", "Asia", RegionType.CONTINENT, id=2),
        3: Region("MARKET", "Market", RegionType.MARKET_REGION, id=3),
    }
    with pytest.raises(DomainValidationError, match=message):
        validate_relationship(regions, (), RegionRelationship(parent_id, child_id))


def test_region_rejects_self_parent() -> None:
    with pytest.raises(DomainValidationError, match="cannot contain itself"):
        RegionRelationship(1, 1)


def test_region_rejects_cycle_and_duplicate_relationship() -> None:
    regions = {
        1: Region("GLOBAL", "Global", RegionType.GLOBAL, id=1),
        2: Region("ASIA", "Asia", RegionType.CONTINENT, id=2),
        3: Region("JP", "Japan", RegionType.COUNTRY, id=3),
    }
    with pytest.raises(DomainValidationError, match="cannot contain"):
        validate_relationship(
            regions,
            (RegionRelationship(1, 2), RegionRelationship(2, 3)),
            RegionRelationship(3, 1),
        )
    with pytest.raises(DomainValidationError, match="Duplicate"):
        validate_relationship(
            regions, (RegionRelationship(1, 2),), RegionRelationship(1, 2)
        )
