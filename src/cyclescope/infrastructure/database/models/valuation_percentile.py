"""Append-only historical valuation percentile result mappings."""

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
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cyclescope.infrastructure.database.base import Base, TimestampMixin
from cyclescope.infrastructure.database.models.normalized_earnings import (
    NormalizedEarningsResultModel,
)
from cyclescope.infrastructure.database.models.valuation import (
    HistoricalValuationMetricModel,
)


class ValuationPercentileResultModel(TimestampMixin, Base):
    __tablename__ = "valuation_percentile_results"
    __table_args__ = (
        CheckConstraint(
            "metric IN ('PER','PBR','EV_EBITDA','NORMALIZED_PER',"
            "'NORMALIZED_EV_EBITDA')",
            name="metric",
        ),
        CheckConstraint(
            "lookback_period IN ('3Y','5Y','10Y','AVAILABLE_HISTORY')", name="lookback"
        ),
        CheckConstraint("method = 'ECDF'", name="method"),
        CheckConstraint(
            "status IN ('AVAILABLE','INSUFFICIENT_DATA','INVALID_INPUT','UNAVAILABLE')",
            name="status",
        ),
        CheckConstraint(
            "(status = 'AVAILABLE' AND percentile IS NOT NULL) OR "
            "(status <> 'AVAILABLE' AND percentile IS NULL)",
            name="status_value",
        ),
        CheckConstraint(
            "percentile IS NULL OR percentile BETWEEN 0 AND 100",
            name="percentile_range",
        ),
        CheckConstraint(
            "valid_observations >= 0 AND excluded_observations >= 0", name="counts"
        ),
        CheckConstraint(
            "coverage_ratio IS NULL OR coverage_ratio BETWEEN 0 AND 1", name="coverage"
        ),
        CheckConstraint("calculation_version >= 1", name="version"),
        CheckConstraint("currency IS NULL OR length(currency) = 3", name="currency"),
        CheckConstraint("unit = 'RATIO'", name="unit"),
        Index("ix_valuation_percentile_security_asof", "security_id", "as_of"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT"), nullable=False
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    lookback_period: Mapped[str] = mapped_column(String(24), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_start: Mapped[date | None] = mapped_column(Date)
    observation_end: Mapped[date | None] = mapped_column(Date)
    current_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    percentile: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    historical_minimum: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    historical_maximum: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    historical_median: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    valid_observations: Mapped[int] = mapped_column(nullable=False)
    excluded_observations: Mapped[int] = mapped_column(nullable=False)
    expected_observations: Mapped[int | None] = mapped_column()
    coverage_ratio: Mapped[Decimal | None] = mapped_column(Numeric(8, 7))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[str] = mapped_column(String(24), nullable=False)
    data_quality: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(3))
    unit: Mapped[str] = mapped_column(String(24), nullable=False)
    financial_period: Mapped[str | None] = mapped_column(String(128))
    calculation_version: Mapped[int] = mapped_column(nullable=False)
    status_reason: Mapped[str | None] = mapped_column(String(1000))
    input_rows: Mapped[list["ValuationPercentileInputModel"]] = relationship(
        back_populates="result", lazy="selectin", passive_deletes="all"
    )


class ValuationPercentileInputModel(TimestampMixin, Base):
    __tablename__ = "valuation_percentile_inputs"
    __table_args__ = (
        CheckConstraint(
            "valuation_snapshot_id IS NOT NULL OR "
            "normalized_earnings_result_id IS NOT NULL",
            name="at_least_one_parent",
        ),
        Index("ix_valuation_percentile_inputs_result", "result_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    result_id: Mapped[int] = mapped_column(
        ForeignKey("valuation_percentile_results.id", ondelete="RESTRICT"),
        nullable=False,
    )
    result: Mapped[ValuationPercentileResultModel] = relationship(
        back_populates="input_rows"
    )
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    included: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(1000))
    valuation_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("historical_valuation_metrics.id", ondelete="RESTRICT")
    )
    valuation_snapshot: Mapped[HistoricalValuationMetricModel | None] = relationship()
    normalized_earnings_result_id: Mapped[int | None] = mapped_column(
        ForeignKey("normalized_earnings_results.id", ondelete="RESTRICT")
    )
    normalized_earnings_result: Mapped[NormalizedEarningsResultModel | None] = (
        relationship()
    )
    market_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT")
    )
    financial_source_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False)
