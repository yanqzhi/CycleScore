"""SQLAlchemy mappings for region nodes and explicit containment edges."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from cyclescope.infrastructure.database.base import Base, TimestampMixin


class RegionModel(TimestampMixin, Base):
    __tablename__ = "regions"
    __table_args__ = (
        UniqueConstraint("region_code", name="uq_region_code"),
        CheckConstraint(
            "region_type IN ('GLOBAL','CONTINENT','COUNTRY','ECONOMIC_REGION',"
            "'MARKET_REGION','UNSPECIFIED')",
            name="region_type",
        ),
        CheckConstraint("length(trim(region_code)) > 0", name="region_code_valid"),
        CheckConstraint("length(trim(name)) > 0", name="region_name_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    region_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    region_type: Mapped[str] = mapped_column(String(24), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RegionRelationshipModel(TimestampMixin, Base):
    __tablename__ = "region_relationships"
    __table_args__ = (
        UniqueConstraint(
            "parent_region_id",
            "child_region_id",
            "relationship_type",
            name="uq_region_relationship_edge",
        ),
        CheckConstraint("parent_region_id != child_region_id", name="region_not_self"),
        CheckConstraint(
            "relationship_type IN ('CONTAINS','MEMBER_OF')",
            name="region_relationship_type",
        ),
        Index("ix_region_relationships_child", "child_region_id"),
        Index("ix_region_relationships_parent", "parent_region_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_region_id: Mapped[int] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False
    )
    child_region_id: Mapped[int] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False
    )
    relationship_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="CONTAINS"
    )
