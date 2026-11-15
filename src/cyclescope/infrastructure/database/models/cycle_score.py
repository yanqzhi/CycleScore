"""Append-only earnings Cycle Score snapshot mapping."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from cyclescope.infrastructure.database.base import Base, TimestampMixin


class CycleScoreModel(TimestampMixin, Base):
    __tablename__ = "cycle_scores"
    __table_args__ = (
        CheckConstraint("score IS NULL OR score BETWEEN 0 AND 100", name="score_range"),
        CheckConstraint(
            "coverage IS NULL OR coverage BETWEEN 0 AND 1", name="coverage_range"
        ),
        CheckConstraint("calculation_version >= 1", name="calculation_version"),
        CheckConstraint(
            "status IN ('AVAILABLE','PARTIAL','INSUFFICIENT_DATA')", name="status"
        ),
        CheckConstraint(
            "phase IN ('EARLY_RECOVERY','EXPANSION','PEAK','CONTRACTION','TROUGH',"
            "'UNKNOWN')",
            name="phase",
        ),
        CheckConstraint(
            "confidence IN ('HIGH','MEDIUM','LOW','INSUFFICIENT')", name="confidence"
        ),
        CheckConstraint(
            "(status = 'INSUFFICIENT_DATA' AND score IS NULL) OR "
            "(status IN ('AVAILABLE','PARTIAL') AND score IS NOT NULL)",
            name="status_score",
        ),
        Index("ix_cycle_scores_company_asof", "company_id", "as_of"),
        Index("ix_cycle_scores_security_asof", "security_id", "as_of"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    security_id: Mapped[int | None] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT")
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    phase: Mapped[str] = mapped_column(String(24), nullable=False)
    phase_reason: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False)
    coverage: Mapped[Decimal | None] = mapped_column(Numeric(8, 7))
    currency: Mapped[str | None] = mapped_column(String(3))
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT")
    )
    normalized_earnings_result_id: Mapped[int] = mapped_column(
        ForeignKey("normalized_earnings_results.id", ondelete="RESTRICT"),
        nullable=False,
    )
    calculation_version: Mapped[int] = mapped_column(nullable=False)
    config_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    components: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    input_references: Mapped[list[dict[str, object]]] = mapped_column(
        JSON, nullable=False
    )
    status_reason: Mapped[str | None] = mapped_column(Text)
