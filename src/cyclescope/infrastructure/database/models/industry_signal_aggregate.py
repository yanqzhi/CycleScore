"""SQLAlchemy tables for append-only industry signal aggregate snapshots."""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from cyclescope.infrastructure.database.base import Base, TimestampMixin


class IndustrySignalAggregateModel(TimestampMixin, Base):
    """One immutable point-in-time aggregation result."""

    __tablename__ = "industry_signal_aggregates"
    __table_args__ = (
        CheckConstraint("industry_id > 0", name="aggregate_industry_positive"),
        CheckConstraint(
            "sub_industry_id IS NULL OR sub_industry_id > 0",
            name="aggregate_sub_industry_positive",
        ),
        CheckConstraint("policy_version >= 1", name="aggregate_policy_version"),
        CheckConstraint(
            "calculation_version >= 1", name="aggregate_calculation_version"
        ),
        CheckConstraint(
            "expected_contributor_count IS NULL OR expected_contributor_count > 0",
            name="aggregate_expected_count",
        ),
        CheckConstraint("actual_contributor_count >= 0", name="aggregate_actual_count"),
        CheckConstraint(
            "coverage_ratio IS NULL OR coverage_ratio BETWEEN 0 AND 1",
            name="aggregate_coverage_range",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="aggregate_confidence_range",
        ),
        CheckConstraint(
            "minimum_coverage BETWEEN 0 AND 1", name="aggregate_minimum_coverage"
        ),
        CheckConstraint(
            "scope_complete = 0 OR aggregate_region_id IS NOT NULL",
            name="aggregate_complete_scope_identity",
        ),
        CheckConstraint(
            "status IN ('AVAILABLE','PARTIAL','INSUFFICIENT_DATA')",
            name="aggregate_status",
        ),
        CheckConstraint(
            "operation IN ('SUM','CAPACITY_WEIGHTED_AVERAGE')",
            name="aggregate_operation",
        ),
        CheckConstraint(
            "(status = 'INSUFFICIENT_DATA' AND value IS NULL) OR "
            "(status != 'INSUFFICIENT_DATA' AND value IS NOT NULL)",
            name="aggregate_value_status",
        ),
        CheckConstraint(
            "(temporal_kind = 'PERIOD' AND observation_date IS NULL "
            "AND period_start IS NOT NULL AND period_end IS NOT NULL "
            "AND period_start <= period_end) OR "
            "(temporal_kind = 'POINT' AND observation_date IS NOT NULL "
            "AND period_start IS NULL AND period_end IS NULL)",
            name="aggregate_temporal_shape",
        ),
        CheckConstraint(
            "(unit_code = 'CURRENCY' AND currency_code IS NOT NULL "
            "AND length(currency_code) = 3 AND upper(currency_code) = currency_code) "
            "OR (unit_code != 'CURRENCY' AND currency_code IS NULL)",
            name="aggregate_currency_unit",
        ),
        Index(
            "ix_industry_signal_aggregates_lookup",
            "industry_id",
            "signal_type",
            "aggregate_region_code",
            "as_of",
        ),
        Index("ix_industry_signal_aggregates_source", "source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    industry_id: Mapped[int] = mapped_column(
        ForeignKey("industries.id", ondelete="RESTRICT"), nullable=False
    )
    sub_industry_id: Mapped[int | None] = mapped_column(
        ForeignKey("sub_industries.id", ondelete="RESTRICT")
    )
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    temporal_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    aggregate_region_code: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_region_id: Mapped[int | None] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT")
    )
    scope_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT")
    )
    unit_code: Mapped[str] = mapped_column(String(24), nullable=False)
    currency_code: Mapped[str | None] = mapped_column(String(3))
    observation_date: Mapped[date | None] = mapped_column(Date)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    policy_code: Mapped[str] = mapped_column(String(48), nullable=False)
    policy_version: Mapped[int] = mapped_column(Integer, nullable=False)
    calculation_version: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    minimum_coverage: Mapped[Decimal] = mapped_column(Numeric(8, 7), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    expected_contributor_count: Mapped[int | None] = mapped_column(Integer)
    actual_contributor_count: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 7))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(8, 7))
    missing_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    validation_warnings: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class IndustrySignalAggregateScopeModel(TimestampMixin, Base):
    """Persisted requested aggregate scope identities in deterministic roles."""

    __tablename__ = "industry_signal_aggregate_scopes"
    __table_args__ = (
        UniqueConstraint(
            "aggregate_id", "region_id", "scope_role", name="uq_signal_aggregate_scope"
        ),
        CheckConstraint(
            "scope_role IN ('AGGREGATE','CONSTITUENT')", name="aggregate_scope_role"
        ),
        Index(
            "ix_signal_aggregate_scopes_order",
            "aggregate_id",
            "scope_role",
            "region_code",
            "region_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    aggregate_id: Mapped[int] = mapped_column(
        ForeignKey("industry_signal_aggregates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    region_id: Mapped[int] = mapped_column(
        ForeignKey("regions.id", ondelete="RESTRICT"), nullable=False
    )
    region_code: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_role: Mapped[str] = mapped_column(String(16), nullable=False)


class IndustrySignalAggregateContributorModel(TimestampMixin, Base):
    """Exact observation provenance used or excluded by an aggregate."""

    __tablename__ = "industry_signal_aggregate_contributors"
    __table_args__ = (
        UniqueConstraint(
            "aggregate_id",
            "observation_id",
            "input_role",
            name="uq_signal_aggregate_contributor_role",
        ),
        CheckConstraint("revision_number >= 1", name="contributor_revision_positive"),
        CheckConstraint(
            "input_role IN ('MEASURE','CAPACITY_WEIGHT')", name="contributor_role"
        ),
        CheckConstraint(
            "(classification_version_id IS NULL AND classification_mapping_id IS NULL) "
            "OR (classification_version_id IS NOT NULL "
            "AND classification_mapping_id IS NOT NULL)",
            name="contributor_classification_pair",
        ),
        CheckConstraint(
            "(included = 1 AND exclusion_reason IS NULL) OR "
            "(included = 0 AND exclusion_reason IS NOT NULL "
            "AND length(trim(exclusion_reason)) > 0)",
            name="contributor_inclusion_reason",
        ),
        CheckConstraint(
            "calculation_weight IS NULL OR calculation_weight >= 0",
            name="contributor_weight_nonnegative",
        ),
        Index("ix_signal_aggregate_contributors_observation", "observation_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    aggregate_id: Mapped[int] = mapped_column(
        ForeignKey("industry_signal_aggregates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    observation_id: Mapped[int] = mapped_column(
        ForeignKey("industry_signal_observations.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    region_code: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_date: Mapped[date | None] = mapped_column(Date)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    publication_date: Mapped[date] = mapped_column(Date, nullable=False)
    publication_datetime: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_reference: Mapped[str | None] = mapped_column(String(500))
    input_role: Mapped[str] = mapped_column(String(24), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    unit_code: Mapped[str] = mapped_column(String(24), nullable=False)
    currency_code: Mapped[str | None] = mapped_column(String(3))
    classification_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("classification_versions.id", ondelete="RESTRICT")
    )
    classification_mapping_id: Mapped[int | None] = mapped_column(
        ForeignKey("industry_classification_mappings.id", ondelete="RESTRICT")
    )
    included: Mapped[bool] = mapped_column(Boolean, nullable=False)
    calculation_weight: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
