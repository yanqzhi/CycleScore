"""Append-only Industry Supply & Demand persistence models."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from cyclescope.infrastructure.database.base import Base, TimestampMixin


class IndustrySupplyDemandSnapshotModel(TimestampMixin, Base):
    __tablename__ = "industry_supply_demand_snapshots"
    __table_args__ = (
        CheckConstraint("industry_id > 0", name="supply_demand_industry_positive"),
        CheckConstraint("config_version > 0", name="supply_demand_config_version"),
        CheckConstraint(
            "coverage IS NULL OR coverage BETWEEN 0 AND 1",
            name="supply_demand_coverage",
        ),
        CheckConstraint(
            "evidence_coverage BETWEEN 0 AND 1",
            name="supply_demand_evidence_coverage",
        ),
        CheckConstraint(
            "inventory_coverage IS NULL OR inventory_coverage BETWEEN 0 AND 1",
            name="supply_demand_inventory_coverage",
        ),
        CheckConstraint(
            "inventory_confidence IS NULL OR inventory_confidence BETWEEN 0 AND 1",
            name="supply_demand_inventory_confidence",
        ),
        CheckConstraint(
            "confidence IS NULL", name="supply_demand_v1_confidence_unknown"
        ),
        CheckConstraint(
            "status IN ('AVAILABLE','PARTIAL','INSUFFICIENT_DATA')",
            name="supply_demand_status",
        ),
        CheckConstraint(
            "phase IN ('DEMAND_RECOVERY','EXPANSION','BALANCED','OVERSUPPLY',"
            "'DEMAND_SLOWDOWN','UNDERSUPPLY','UNKNOWN')",
            name="supply_demand_phase",
        ),
        Index(
            "ix_industry_supply_demand_lookup",
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
    aggregate_region_id: Mapped[int | None] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT")
    )
    aggregate_region_code: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT")
    )
    unit_code: Mapped[str | None] = mapped_column(String(24))
    currency_code: Mapped[str | None] = mapped_column(String(3))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    observation_date: Mapped[date | None] = mapped_column(Date)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    phase: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    production_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    shipments_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    flow_gap: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    flow_gap_ratio: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    shipment_growth_yoy: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    inventory_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("industry_inventory_snapshots.id", ondelete="RESTRICT")
    )
    inventory_classification: Mapped[str | None] = mapped_column(String(32))
    inventory_trend: Mapped[str | None] = mapped_column(String(16))
    inventory_yoy_growth: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    inventory_growth_acceleration: Mapped[Decimal | None] = mapped_column(
        Numeric(38, 12)
    )
    inventory_coverage: Mapped[Decimal | None] = mapped_column(Numeric(8, 7))
    inventory_confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 7))
    coverage: Mapped[Decimal | None] = mapped_column(Numeric(8, 7))
    evidence_coverage: Mapped[Decimal] = mapped_column(Numeric(8, 7), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 7))
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    config_snapshot: Mapped[dict[str, str | int]] = mapped_column(JSON, nullable=False)
    unavailable_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    validation_warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class IndustrySupplyDemandInputModel(TimestampMixin, Base):
    __tablename__ = "industry_supply_demand_inputs"
    __table_args__ = (
        CheckConstraint(
            "(aggregate_id IS NOT NULL AND inventory_snapshot_id IS NULL) OR "
            "(aggregate_id IS NULL AND inventory_snapshot_id IS NOT NULL)",
            name="supply_demand_input_exactly_one_source",
        ),
        CheckConstraint(
            "coverage IS NULL OR coverage BETWEEN 0 AND 1",
            name="supply_demand_input_coverage",
        ),
        CheckConstraint(
            "(included = 1 AND exclusion_reason IS NULL) OR "
            "(included = 0 AND exclusion_reason IS NOT NULL "
            "AND length(trim(exclusion_reason)) > 0)",
            name="supply_demand_input_inclusion_reason",
        ),
        UniqueConstraint(
            "snapshot_id",
            "aggregate_id",
            "inventory_snapshot_id",
            "role",
            name="uq_industry_supply_demand_input",
        ),
        Index("ix_industry_supply_demand_inputs_aggregate", "aggregate_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("industry_supply_demand_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    aggregate_id: Mapped[int | None] = mapped_column(
        ForeignKey("industry_signal_aggregates.id", ondelete="RESTRICT")
    )
    inventory_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("industry_inventory_snapshots.id", ondelete="RESTRICT")
    )
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT")
    )
    unit_code: Mapped[str | None] = mapped_column(String(24))
    currency_code: Mapped[str | None] = mapped_column(String(3))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    contributing_regions: Mapped[list[dict[str, int | str]]] = mapped_column(
        JSON, nullable=False
    )
    coverage: Mapped[Decimal | None] = mapped_column(Numeric(8, 7))
    policy_code: Mapped[str | None] = mapped_column(String(48))
    policy_version: Mapped[int | None] = mapped_column(Integer)
    calculation_version: Mapped[int | None] = mapped_column(Integer)
    classification_references: Mapped[list[list[int | None]]] = mapped_column(
        JSON, nullable=False
    )
    contributor_revisions: Mapped[list[list[int]]] = mapped_column(JSON, nullable=False)
    included: Mapped[bool] = mapped_column(Boolean, nullable=False)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)


class IndustrySupplyDemandScopeModel(TimestampMixin, Base):
    __tablename__ = "industry_supply_demand_scopes"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "region_id",
            "scope_role",
            name="uq_industry_supply_demand_scope",
        ),
        CheckConstraint(
            "scope_role IN ('REQUESTED','CONTRIBUTING')",
            name="supply_demand_scope_role",
        ),
        Index(
            "ix_industry_supply_demand_scopes_order",
            "snapshot_id",
            "scope_role",
            "region_code",
            "region_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("industry_supply_demand_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    region_id: Mapped[int] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False
    )
    region_code: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_role: Mapped[str] = mapped_column(String(16), nullable=False)
