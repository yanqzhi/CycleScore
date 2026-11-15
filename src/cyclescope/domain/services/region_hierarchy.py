"""Deterministic validation and traversal of the multi-parent region graph."""

from collections import deque

from cyclescope.domain.entities.region import (
    Region,
    RegionRelationship,
    RegionRelationshipType,
    validate_region_relationship_types,
)
from cyclescope.domain.exceptions import DomainValidationError


def validate_relationship(
    regions: dict[int, Region],
    relationships: tuple[RegionRelationship, ...],
    candidate: RegionRelationship | None = None,
) -> None:
    """Validate endpoints and edge meaning; only containment forms a hierarchy."""
    edges = list(relationships)
    if candidate is not None:
        edges.append(candidate)
    seen: set[tuple[int, int, object]] = set()
    adjacency: dict[int, list[int]] = {region_id: [] for region_id in regions}
    for edge in edges:
        parent = regions.get(edge.parent_region_id)
        child = regions.get(edge.child_region_id)
        if parent is None or child is None:
            raise DomainValidationError(
                "Region relationship references unknown region."
            )
        key = (edge.parent_region_id, edge.child_region_id, edge.relationship_type)
        if key in seen:
            raise DomainValidationError("Duplicate region relationship.")
        seen.add(key)
        if edge.relationship_type is RegionRelationshipType.CONTAINS:
            adjacency[edge.parent_region_id].append(edge.child_region_id)
    color: dict[int, int] = {}

    def visit(node: int) -> None:
        state = color.get(node, 0)
        if state == 1:
            raise DomainValidationError("Region relationships cannot contain cycles.")
        if state == 2:
            return
        color[node] = 1
        for child in sorted(adjacency[node]):
            visit(child)
        color[node] = 2

    for region_id in sorted(regions):
        visit(region_id)
    for edge in edges:
        parent = regions[edge.parent_region_id]
        child = regions[edge.child_region_id]
        validate_region_relationship_types(
            parent.region_type, child.region_type, edge.relationship_type
        )


def descendants(
    region_id: int,
    regions: dict[int, Region],
    relationships: tuple[RegionRelationship, ...],
) -> tuple[Region, ...]:
    """Return unique descendants in deterministic region-code order."""
    if region_id not in regions:
        raise DomainValidationError("Unknown region.")
    children: dict[int, set[int]] = {key: set() for key in regions}
    for relation in relationships:
        if relation.relationship_type is RegionRelationshipType.CONTAINS:
            children[relation.parent_region_id].add(relation.child_region_id)
    found: set[int] = set()
    pending = deque(sorted(children[region_id]))
    while pending:
        child = pending.popleft()
        if child in found:
            continue
        found.add(child)
        pending.extend(sorted(children[child]))
    return tuple(
        sorted((regions[key] for key in found), key=lambda item: item.region_code)
    )


def ancestor_paths(
    region_id: int,
    regions: dict[int, Region],
    relationships: tuple[RegionRelationship, ...],
) -> tuple[tuple[Region, ...], ...]:
    """Return all root-to-parent paths ordered by their region-code tuples."""
    if region_id not in regions:
        raise DomainValidationError("Unknown region.")
    parents: dict[int, set[int]] = {key: set() for key in regions}
    for relation in relationships:
        if relation.relationship_type is RegionRelationshipType.CONTAINS:
            parents[relation.child_region_id].add(relation.parent_region_id)

    def paths_to(node: int, trail: frozenset[int]) -> list[tuple[int, ...]]:
        if node in trail:
            raise DomainValidationError("Region relationships cannot contain cycles.")
        if not parents[node]:
            return [()]
        paths: list[tuple[int, ...]] = []
        for parent_id in sorted(
            parents[node], key=lambda key: regions[key].region_code
        ):
            for prefix in paths_to(parent_id, trail | {node}):
                paths.append((*prefix, parent_id))
        return paths

    if not parents[region_id]:
        return ()
    raw_paths = paths_to(region_id, frozenset())
    ordered = sorted(
        set(raw_paths),
        key=lambda path: tuple(regions[item].region_code for item in path),
    )
    return tuple(tuple(regions[item] for item in path) for path in ordered)


def is_descendant(
    region_id: int,
    ancestor_id: int,
    regions: dict[int, Region],
    relationships: tuple[RegionRelationship, ...],
) -> bool:
    """Return whether region_id is a strict descendant through real edges."""
    return any(
        item.id == region_id
        for item in descendants(ancestor_id, regions, relationships)
    )
