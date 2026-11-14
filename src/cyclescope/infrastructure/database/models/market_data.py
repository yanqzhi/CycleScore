"""SQLAlchemy mappings for immutable market-data observations."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
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


class DailyPriceModel(TimestampMixin, Base):
    """One immutable daily OHLCV observation and source revision."""

    __tablename__ = "daily_prices"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "observation_date",
            "source_id",
            "revision_number",
            name="uq_daily_prices_observation_revision",
        ),
        CheckConstraint(
            "open >= 0 AND high >= 0 AND low >= 0 AND close >= 0",
            name="price_values_nonnegative",
        ),
        CheckConstraint(
            "adjusted_close IS NULL OR adjusted_close >= 0",
            name="adjusted_close_nonnegative",
        ),
        CheckConstraint(
            "high >= open AND high >= close AND high >= low",
            name="high_relationship",
        ),
        CheckConstraint("low <= open AND low <= close", name="low_relationship"),
        CheckConstraint("volume >= 0", name="volume_nonnegative"),
        CheckConstraint("revision_number >= 1", name="revision_positive"),
        Index("ix_daily_prices_security_date", "security_id", "observation_date"),
        Index(
            "ix_daily_prices_security_source_date_asof_revision",
            "security_id",
            "source_id",
            "observation_date",
            "available_at",
            "revision_number",
        ),
        Index("ix_daily_prices_observation_date", "observation_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT"), nullable=False
    )
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    adjusted_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    publication_date: Mapped[date | None] = mapped_column(Date)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)


class FxRateModel(TimestampMixin, Base):
    """One immutable FX observation and source revision."""

    __tablename__ = "fx_rates"
    __table_args__ = (
        UniqueConstraint(
            "base_currency",
            "quote_currency",
            "observation_date",
            "source_id",
            "revision_number",
            name="uq_fx_rates_observation_revision",
        ),
        CheckConstraint(
            "base_currency <> quote_currency", name="currency_pair_distinct"
        ),
        CheckConstraint("rate > 0", name="rate_positive"),
        CheckConstraint("revision_number >= 1", name="revision_positive"),
        Index(
            "ix_fx_rates_pair_date",
            "base_currency",
            "quote_currency",
            "observation_date",
        ),
        Index(
            "ix_fx_rates_pair_source_date_asof_revision",
            "base_currency",
            "quote_currency",
            "source_id",
            "observation_date",
            "available_at",
            "revision_number",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(24, 12), nullable=False)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    publication_date: Mapped[date | None] = mapped_column(Date)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
