"""Append-only normalized earnings analysis persistence mappings."""

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cyclescope.infrastructure.database.base import Base, TimestampMixin


class NormalizedEarningsResultModel(TimestampMixin, Base):
    __tablename__ = "normalized_earnings_results"
    __table_args__ = (
        CheckConstraint("window_years IN (5, 7, 10)", name="window_years"),
        CheckConstraint("effective_window_years >= 1", name="effective_window"),
        CheckConstraint("calculation_version >= 1", name="version_positive"),
        CheckConstraint("valid_fiscal_years >= 0", name="valid_years"),
        CheckConstraint("loss_making_years >= 0", name="loss_years"),
        CheckConstraint("data_coverage >= 0 AND data_coverage <= 1", name="coverage"),
        CheckConstraint(
            "metric IN ('OPERATING_PROFIT','NET_INCOME','EPS','EBITDA')",
            name="metric",
        ),
        CheckConstraint("method IN ('ARITHMETIC_MEAN','MEDIAN')", name="method"),
        CheckConstraint(
            "confidence IN ('HIGH','MEDIUM','LOW','INSUFFICIENT')",
            name="confidence",
        ),
        CheckConstraint(
            "status IN ('AVAILABLE','INSUFFICIENT_DATA','UNAVAILABLE')",
            name="status",
        ),
        CheckConstraint(
            "(status = 'AVAILABLE' AND normalized_value IS NOT NULL) OR "
            "(status <> 'AVAILABLE' AND normalized_value IS NULL)",
            name="status_value",
        ),
        CheckConstraint(
            "normalized_valuation_status IS NULL OR normalized_valuation_status IN "
            "('AVAILABLE','INSUFFICIENT_DATA','INVALID_INPUT','NOT_APPLICABLE','UNAVAILABLE')",
            name="normalized_valuation_status",
        ),
        CheckConstraint(
            "(normalized_valuation_status = 'AVAILABLE' AND "
            "normalized_valuation_value IS NOT NULL) OR "
            "((normalized_valuation_status IS NULL OR "
            "normalized_valuation_status <> 'AVAILABLE') AND "
            "normalized_valuation_value IS NULL)",
            name="normalized_valuation_status_value",
        ),
        Index(
            "ix_normalized_earnings_company_metric_asof",
            "company_id",
            "metric",
            "as_of",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    security_id: Mapped[int | None] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT")
    )
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    window_years: Mapped[int] = mapped_column(nullable=False)
    effective_window_years: Mapped[int] = mapped_column(nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    status_reason: Mapped[str | None] = mapped_column(String(1000))
    normalized_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    arithmetic_mean: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    median: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    minimum: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    maximum: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    standard_deviation: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    valid_fiscal_years: Mapped[int] = mapped_column(nullable=False)
    loss_making_years: Mapped[int] = mapped_column(nullable=False)
    data_coverage: Mapped[Decimal] = mapped_column(Numeric(8, 7), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    calculation_period_start: Mapped[date | None] = mapped_column(Date)
    calculation_period_end: Mapped[date | None] = mapped_column(Date)
    fiscal_year_values: Mapped[list[dict[str, str | int]]] = mapped_column(
        JSON, nullable=False
    )
    peak_candidate_year: Mapped[int | None] = mapped_column()
    trough_candidate_year: Mapped[int | None] = mapped_column()
    assumptions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    calculation_version: Mapped[int] = mapped_column(nullable=False)
    normalized_valuation_status: Mapped[str | None] = mapped_column(String(24))
    normalized_valuation_reason: Mapped[str | None] = mapped_column(String(1000))
    normalized_valuation_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    input_refs: Mapped[list["NormalizedEarningsInputRefModel"]] = relationship(
        back_populates="result", cascade="all, delete-orphan", lazy="selectin"
    )


class NormalizedEarningsInputRefModel(TimestampMixin, Base):
    __tablename__ = "normalized_earnings_input_refs"
    __table_args__ = (
        CheckConstraint(
            "provenance_kind IN ('EARNINGS','VALUATION')", name="provenance_kind"
        ),
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
        Index("ix_normalized_earnings_input_result", "result_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    result_id: Mapped[int] = mapped_column(
        ForeignKey("normalized_earnings_results.id", ondelete="RESTRICT"),
        nullable=False,
    )
    result: Mapped[NormalizedEarningsResultModel] = relationship(
        back_populates="input_refs"
    )
    provenance_kind: Mapped[str] = mapped_column(String(16), nullable=False)
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
    fiscal_year: Mapped[int | None] = mapped_column()
    fiscal_period: Mapped[str | None] = mapped_column(String(8))
    item_code: Mapped[str | None] = mapped_column(String(80))
    period_end: Mapped[date | None] = mapped_column(Date)
    observation_date: Mapped[date | None] = mapped_column(Date)
    financial_item_code: Mapped[str | None] = mapped_column(String(80))
    financial_period: Mapped[str | None] = mapped_column(String(8))
    period_start: Mapped[date | None] = mapped_column(Date)
    publication_date: Mapped[date | None] = mapped_column(Date)
    publication_datetime: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
