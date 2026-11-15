"""SQLAlchemy mapping for append-only industry signal observations."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from cyclescope.infrastructure.database.base import Base, TimestampMixin


class IndustrySignalObservationModel(TimestampMixin, Base):
    """One immutable industry observation or event revision from one source."""

    __tablename__ = "industry_signal_observations"
    __table_args__ = (
        CheckConstraint("revision_number >= 1", name="revision_positive"),
        CheckConstraint(
            "signal_type IN ('INVENTORY','PRODUCTION','SHIPMENTS','SALES','ORDERS',"
            "'CAPACITY','CAPACITY_UTILIZATION','CAPACITY_ADDITION',"
            "'CAPACITY_CLOSURE_ANNOUNCED','CAPACITY_CLOSURE_COMPLETED')",
            name="signal_type",
        ),
        CheckConstraint(
            "(temporal_kind = 'POINT' AND signal_type IN "
            "('INVENTORY','CAPACITY','CAPACITY_UTILIZATION')) OR "
            "(temporal_kind = 'PERIOD' AND signal_type IN "
            "('PRODUCTION','SHIPMENTS','SALES','ORDERS')) OR "
            "(temporal_kind = 'EVENT' AND signal_type IN "
            "('CAPACITY_ADDITION','CAPACITY_CLOSURE_ANNOUNCED',"
            "'CAPACITY_CLOSURE_COMPLETED'))",
            name="signal_temporal_compatibility",
        ),
        CheckConstraint(
            "(temporal_kind IN ('POINT','EVENT') AND observation_date IS NOT NULL "
            "AND period_start IS NULL AND period_end IS NULL) OR "
            "(temporal_kind = 'PERIOD' AND observation_date IS NULL "
            "AND period_start IS NOT NULL AND period_end IS NOT NULL "
            "AND period_start <= period_end)",
            name="temporal_shape",
        ),
        CheckConstraint(
            "unit_code IN ('TONNE','THOUSAND_TONNE','UNIT','THOUSAND_UNITS',"
            "'CURRENCY','PERCENTAGE','INDEX')",
            name="unit_code",
        ),
        CheckConstraint(
            "(signal_type = 'CAPACITY_UTILIZATION' AND unit_code = 'PERCENTAGE') OR "
            "(signal_type IN ('INVENTORY','SALES','ORDERS') AND unit_code IN "
            "('TONNE','THOUSAND_TONNE','UNIT','THOUSAND_UNITS','CURRENCY','INDEX')) "
            "OR (signal_type IN ('PRODUCTION','SHIPMENTS','CAPACITY',"
            "'CAPACITY_ADDITION','CAPACITY_CLOSURE_ANNOUNCED',"
            "'CAPACITY_CLOSURE_COMPLETED') AND unit_code IN "
            "('TONNE','THOUSAND_TONNE','UNIT','THOUSAND_UNITS'))",
            name="unit_signal_compatibility",
        ),
        CheckConstraint(
            "(unit_code = 'CURRENCY' AND currency_code IS NOT NULL "
            "AND length(currency_code) = 3 AND upper(currency_code) = currency_code) "
            "OR (unit_code != 'CURRENCY' AND currency_code IS NULL)",
            name="currency_unit_compatibility",
        ),
        CheckConstraint(
            "(value IS NOT NULL AND missing_reason IS NULL) OR "
            "(value IS NULL AND missing_reason IS NOT NULL "
            "AND length(trim(missing_reason)) > 0)",
            name="missing_value_reason",
        ),
        CheckConstraint(
            "publication_datetime IS NULL OR available_at >= publication_datetime",
            name="publication_availability_order",
        ),
        CheckConstraint(
            "region_code = trim(region_code) AND length(region_code) BETWEEN 1 AND 64",
            name="region_code_valid",
        ),
        Index(
            "ix_industry_signals_industry_type_point_asof",
            "industry_id",
            "signal_type",
            "observation_date",
            "available_at",
        ),
        Index(
            "ix_industry_signals_industry_type_period_asof",
            "industry_id",
            "signal_type",
            "period_end",
            "available_at",
        ),
        Index(
            "ix_industry_signals_source_availability",
            "source_id",
            "available_at",
        ),
        Index(
            "ix_industry_signals_subindustry_region",
            "sub_industry_id",
            "region_code",
        ),
        Index(
            "uq_industry_signal_point_revision_no_subindustry",
            "industry_id",
            "signal_type",
            "temporal_kind",
            "region_code",
            "observation_date",
            "source_id",
            "revision_number",
            unique=True,
            sqlite_where=text(
                "sub_industry_id IS NULL AND temporal_kind IN ('POINT','EVENT')"
            ),
            postgresql_where=text(
                "sub_industry_id IS NULL AND temporal_kind IN ('POINT','EVENT')"
            ),
        ),
        Index(
            "uq_industry_signal_point_revision_subindustry",
            "industry_id",
            "sub_industry_id",
            "signal_type",
            "temporal_kind",
            "region_code",
            "observation_date",
            "source_id",
            "revision_number",
            unique=True,
            sqlite_where=text(
                "sub_industry_id IS NOT NULL AND temporal_kind IN ('POINT','EVENT')"
            ),
            postgresql_where=text(
                "sub_industry_id IS NOT NULL AND temporal_kind IN ('POINT','EVENT')"
            ),
        ),
        Index(
            "uq_industry_signal_period_revision_no_subindustry",
            "industry_id",
            "signal_type",
            "temporal_kind",
            "region_code",
            "period_start",
            "period_end",
            "source_id",
            "revision_number",
            unique=True,
            sqlite_where=text("sub_industry_id IS NULL AND temporal_kind = 'PERIOD'"),
            postgresql_where=text(
                "sub_industry_id IS NULL AND temporal_kind = 'PERIOD'"
            ),
        ),
        Index(
            "uq_industry_signal_period_revision_subindustry",
            "industry_id",
            "sub_industry_id",
            "signal_type",
            "temporal_kind",
            "region_code",
            "period_start",
            "period_end",
            "source_id",
            "revision_number",
            unique=True,
            sqlite_where=text(
                "sub_industry_id IS NOT NULL AND temporal_kind = 'PERIOD'"
            ),
            postgresql_where=text(
                "sub_industry_id IS NOT NULL AND temporal_kind = 'PERIOD'"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    industry_id: Mapped[int] = mapped_column(
        ForeignKey("industries.id", ondelete="RESTRICT"), nullable=False
    )
    sub_industry_id: Mapped[int | None] = mapped_column(
        ForeignKey("sub_industries.id", ondelete="RESTRICT")
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    signal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    temporal_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    region_code: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_date: Mapped[date | None] = mapped_column(Date)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    unit_code: Mapped[str] = mapped_column(String(24), nullable=False)
    currency_code: Mapped[str | None] = mapped_column(String(3))
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
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_reference: Mapped[str | None] = mapped_column(String(500))
    missing_reason: Mapped[str | None] = mapped_column(String(500))
