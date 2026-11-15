"""SQLAlchemy mapping for append-only inventory calculation snapshots."""

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
)
from sqlalchemy.orm import Mapped, mapped_column

from cyclescope.infrastructure.database.base import Base, TimestampMixin


class InventorySnapshotModel(TimestampMixin, Base):
    __tablename__ = "inventory_snapshots"
    __table_args__ = (
        CheckConstraint("data_coverage BETWEEN 0 AND 1", name="coverage_range"),
        CheckConstraint("calculation_version >= 1", name="calculation_version"),
        CheckConstraint(
            "status IN ('AVAILABLE','PARTIAL','INSUFFICIENT_DATA','UNAVAILABLE')",
            name="status",
        ),
        CheckConstraint(
            "trend IN ('INCREASING','DECREASING','STABLE','VOLATILE','UNKNOWN')",
            name="trend",
        ),
        CheckConstraint("fiscal_year >= 1", name="fiscal_year"),
        Index("ix_inventory_snapshots_company_asof", "company_id", "as_of"),
        Index(
            "ix_inventory_snapshots_company_year", "company_id", "fiscal_year", "as_of"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    security_id: Mapped[int | None] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT")
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    closing_inventory: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    opening_inventory: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    average_inventory: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    cogs: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    inventory_change: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    inventory_growth: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    inventory_turnover: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    dio: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    trend: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    unavailable_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    data_coverage: Mapped[Decimal] = mapped_column(Numeric(8, 7), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    calculation_version: Mapped[int] = mapped_column(nullable=False)
    config_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    input_references: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False
    )
