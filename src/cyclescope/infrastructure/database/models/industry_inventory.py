"""Append-only persistence models for industry inventory analysis."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from cyclescope.infrastructure.database.base import Base, TimestampMixin


class IndustryInventorySnapshotModel(TimestampMixin, Base):
    __tablename__ = "industry_inventory_snapshots"
    __table_args__ = (
        CheckConstraint("industry_id > 0", name="industry_inventory_industry_positive"),
        CheckConstraint("config_version > 0", name="industry_inventory_config_version"),
        CheckConstraint(
            "coverage IS NULL OR coverage BETWEEN 0 AND 1",
            name="industry_inventory_coverage",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="industry_inventory_confidence",
        ),
        CheckConstraint(
            "status IN ('AVAILABLE','PARTIAL','INSUFFICIENT_DATA')",
            name="industry_inventory_status",
        ),
        CheckConstraint(
            "trend IN ('INCREASING','DECREASING','STABLE','UNKNOWN')",
            name="industry_inventory_trend",
        ),
        Index(
            "ix_industry_inventory_lookup",
            "industry_id",
            "aggregate_region_code",
            "as_of",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    industry_id: Mapped[int] = mapped_column(
        ForeignKey("industries.id", ondelete="RESTRICT"), nullable=False
    )
    sub_industry_id: Mapped[int | None] = mapped_column(
        ForeignKey("sub_industries.id", ondelete="RESTRICT")
    )
    aggregate_region_code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT")
    )
    unit_code: Mapped[str] = mapped_column(String(24), nullable=False)
    currency_code: Mapped[str | None] = mapped_column(String(3))
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    trend: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    inventory_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    prior_inventory_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    absolute_change: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    yoy_growth: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    prior_yoy_growth: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    growth_acceleration: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    production_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    shipments_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    production_shipment_gap: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    coverage: Mapped[Decimal | None] = mapped_column(Numeric(8, 7))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 7))
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    config_snapshot: Mapped[dict[str, str | int]] = mapped_column(JSON, nullable=False)
    unavailable_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class IndustryInventoryScopeModel(TimestampMixin, Base):
    """Requested and actual regional identities, including missing regions."""

    __tablename__ = "industry_inventory_scopes"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "region_id", "scope_role", name="uq_industry_inventory_scope"
        ),
        CheckConstraint(
            "scope_role IN ('REQUESTED','CONTRIBUTING')",
            name="industry_inventory_scope_role",
        ),
        Index(
            "ix_industry_inventory_scopes_order",
            "snapshot_id",
            "scope_role",
            "region_code",
            "region_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("industry_inventory_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    region_id: Mapped[int] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False
    )
    region_code: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_role: Mapped[str] = mapped_column(String(16), nullable=False)


class IndustryInventoryInputModel(TimestampMixin, Base):
    __tablename__ = "industry_inventory_inputs"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "aggregate_id", "role", name="uq_industry_inventory_input"
        ),
        CheckConstraint(
            "role IN ('CURRENT_INVENTORY','PRIOR_INVENTORY','YEAR_PRIOR_INVENTORY',"
            "'PRIOR_YEAR_PRIOR_INVENTORY','PRODUCTION','SHIPMENTS')",
            name="industry_inventory_input_role",
        ),
        Index("ix_industry_inventory_inputs_aggregate", "aggregate_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("industry_inventory_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    aggregate_id: Mapped[int] = mapped_column(
        ForeignKey("industry_signal_aggregates.id", ondelete="RESTRICT"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    observation_date: Mapped[date | None] = mapped_column(Date)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT")
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    contributor_revisions: Mapped[list[list[int]]] = mapped_column(JSON, nullable=False)
