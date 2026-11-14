"""Persistence mappings for metric definitions and historical values."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cyclescope.infrastructure.database.base import Base, TimestampMixin


class ValuationMetricModel(TimestampMixin, Base):
    __tablename__ = "valuation_metrics"
    __table_args__ = (
        UniqueConstraint("metric_code", name="uq_valuation_metric_code"),
        CheckConstraint("unit IN ('RATIO','PER_SHARE','CURRENCY_AMOUNT')", name="unit"),
        CheckConstraint(
            "currency_applicability IN ('NONE','MARKET_CURRENCY')",
            name="currency_applicability",
        ),
        CheckConstraint("calculation_version >= 1", name="version_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    metric_code: Mapped[str] = mapped_column(String(40), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    unit: Mapped[str] = mapped_column(String(24), nullable=False)
    currency_applicability: Mapped[str] = mapped_column(String(24), nullable=False)
    required_inputs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    calculation_method: Mapped[str] = mapped_column(String(80), nullable=False)
    calculation_version: Mapped[int] = mapped_column(nullable=False)
    validity_rules: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class HistoricalValuationMetricModel(TimestampMixin, Base):
    __tablename__ = "historical_valuation_metrics"
    __table_args__ = (
        CheckConstraint(
            "status IN ('AVAILABLE','INSUFFICIENT_DATA','INVALID_INPUT',"
            "'NOT_APPLICABLE','UNAVAILABLE')",
            name="status",
        ),
        CheckConstraint(
            "(status = 'AVAILABLE' AND value IS NOT NULL) OR "
            "(status <> 'AVAILABLE' AND value IS NULL)",
            name="status_value_consistency",
        ),
        CheckConstraint("calculation_version >= 1", name="version_positive"),
        Index(
            "ix_historical_valuation_metric_security_date_asof",
            "security_id",
            "metric_id",
            "observation_date",
            "as_of",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT"), nullable=False
    )
    metric_id: Mapped[int] = mapped_column(
        ForeignKey("valuation_metrics.id", ondelete="RESTRICT"), nullable=False
    )
    metric: Mapped[ValuationMetricModel] = relationship()
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    currency: Mapped[str | None] = mapped_column(String(3))
    unit: Mapped[str] = mapped_column(String(24), nullable=False)
    financial_period: Mapped[str | None] = mapped_column(String(128))
    eps_calculation_method: Mapped[str | None] = mapped_column(String(64))
    calculation_version: Mapped[int] = mapped_column(nullable=False)
    price_observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_prices.id", ondelete="RESTRICT")
    )
    price_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT")
    )
    price_revision_number: Mapped[int | None] = mapped_column()
    price_available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    financial_statement_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    financial_source_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
    financial_statement_available_ats: Mapped[list[str]] = mapped_column(
        JSON, nullable=False
    )
    input_snapshot: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    input_reference_rows: Mapped[list["ValuationSnapshotInputModel"]] = relationship(
        back_populates="snapshot"
    )
    unavailable_inputs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    unavailable_reason: Mapped[str | None] = mapped_column(String(1000))


class ValuationSnapshotInputModel(TimestampMixin, Base):
    """Referentially constrained provenance for one persisted metric input."""

    __tablename__ = "valuation_snapshot_inputs"
    __table_args__ = (
        CheckConstraint(
            "(record_type = 'DAILY_PRICE' AND market_price_id IS NOT NULL "
            "AND financial_statement_id IS NULL "
            "AND financial_statement_item_id IS NULL) OR "
            "(record_type = 'FINANCIAL_LINE' AND market_price_id IS NULL "
            "AND financial_statement_id IS NOT NULL "
            "AND financial_statement_item_id IS NOT NULL)",
            name="record_reference_consistency",
        ),
        CheckConstraint("revision_number >= 1", name="revision_positive"),
        Index("ix_valuation_snapshot_inputs_snapshot", "snapshot_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("historical_valuation_metrics.id", ondelete="RESTRICT"),
        nullable=False,
    )
    snapshot: Mapped[HistoricalValuationMetricModel] = relationship(
        back_populates="input_reference_rows"
    )
    record_type: Mapped[str] = mapped_column(String(24), nullable=False)
    market_price_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_prices.id", ondelete="RESTRICT")
    )
    financial_statement_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_statements.id", ondelete="RESTRICT")
    )
    financial_statement_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("financial_statement_items.id", ondelete="RESTRICT")
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    observation_date: Mapped[date | None] = mapped_column(Date)
    financial_item_code: Mapped[str | None] = mapped_column(String(80))
    financial_period: Mapped[str | None] = mapped_column(String(8))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    publication_date: Mapped[date | None] = mapped_column(Date)
    publication_datetime: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
