"""SQLAlchemy adapters for region nodes and containment relationships."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from cyclescope.domain.entities.region import (
    Region,
    RegionRelationship,
    RegionRelationshipType,
    RegionType,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    RegionRelationshipRepository,
    RegionRepository,
)
from cyclescope.infrastructure.database.models.region import (
    RegionModel,
    RegionRelationshipModel,
)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _region(row: RegionModel) -> Region:
    return Region(
        id=row.id,
        region_code=row.region_code,
        name=row.name,
        region_type=RegionType(row.region_type),
        country_code=row.country_code,
        is_active=row.is_active,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


def _relationship(row: RegionRelationshipModel) -> RegionRelationship:
    return RegionRelationship(
        id=row.id,
        parent_region_id=row.parent_region_id,
        child_region_id=row.child_region_id,
        relationship_type=RegionRelationshipType(row.relationship_type),
        created_at=_utc(row.created_at),
    )


class SQLAlchemyRegionRepository(RegionRepository):
    """Append/read adapter for region identities."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, region: Region) -> Region:
        if self.get_by_code(region.region_code) is not None:
            raise DomainValidationError("Region code already exists.")
        row = RegionModel(
            region_code=region.region_code,
            name=region.name,
            region_type=region.region_type.value,
            country_code=region.country_code,
            is_active=region.is_active,
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _region(row)

    def get_by_id(self, region_id: int) -> Region | None:
        row = self._session.get(RegionModel, region_id)
        return _region(row) if row is not None else None

    def get_by_code(self, region_code: str) -> Region | None:
        row = self._session.scalar(
            select(RegionModel).where(RegionModel.region_code == region_code)
        )
        return _region(row) if row is not None else None

    def list(self) -> list[Region]:
        rows = self._session.scalars(
            select(RegionModel).order_by(RegionModel.region_code)
        )
        return [_region(row) for row in rows]


class SQLAlchemyRegionRelationshipRepository(RegionRelationshipRepository):
    """Append/read adapter for multi-parent region containment edges."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, relationship: RegionRelationship) -> RegionRelationship:
        if self.exists(relationship):
            raise DomainValidationError("Region relationship already exists.")
        row = RegionRelationshipModel(
            parent_region_id=relationship.parent_region_id,
            child_region_id=relationship.child_region_id,
            relationship_type=relationship.relationship_type.value,
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _relationship(row)

    def exists(self, relationship: RegionRelationship) -> bool:
        return (
            self._session.scalar(
                select(RegionRelationshipModel.id).where(
                    RegionRelationshipModel.parent_region_id
                    == relationship.parent_region_id,
                    RegionRelationshipModel.child_region_id
                    == relationship.child_region_id,
                    RegionRelationshipModel.relationship_type
                    == relationship.relationship_type.value,
                )
            )
            is not None
        )

    def list_all(self) -> list[RegionRelationship]:
        rows = self._session.scalars(
            select(RegionRelationshipModel).order_by(
                RegionRelationshipModel.parent_region_id,
                RegionRelationshipModel.child_region_id,
                RegionRelationshipModel.id,
            )
        )
        return [_relationship(row) for row in rows]

    def list_by_parent(self, parent_region_id: int) -> list[RegionRelationship]:
        rows = self._session.scalars(
            select(RegionRelationshipModel)
            .where(RegionRelationshipModel.parent_region_id == parent_region_id)
            .order_by(RegionRelationshipModel.child_region_id)
        )
        return [_relationship(row) for row in rows]

    def list_by_child(self, child_region_id: int) -> list[RegionRelationship]:
        rows = self._session.scalars(
            select(RegionRelationshipModel)
            .where(RegionRelationshipModel.child_region_id == child_region_id)
            .order_by(RegionRelationshipModel.parent_region_id)
        )
        return [_relationship(row) for row in rows]
