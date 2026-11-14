"""Append-only Value Score database snapshot."""

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
)
from sqlalchemy.orm import Mapped, mapped_column

from cyclescope.infrastructure.database.base import Base, TimestampMixin


class ValueScoreModel(TimestampMixin, Base):
    __tablename__ = "value_scores"
    __table_args__ = (
        CheckConstraint("score IS NULL OR score BETWEEN 0 AND 100", name="score_range"),
        CheckConstraint("coverage BETWEEN 0 AND 1", name="coverage_range"),
        CheckConstraint("config_version >= 1", name="config_version"),
        CheckConstraint(
            "(status = 'INSUFFICIENT_DATA' AND score IS NULL) OR "
            "(status IN ('AVAILABLE','PARTIAL') AND score IS NOT NULL)",
            name="status_score",
        ),
        Index("ix_value_scores_security_asof", "security_id", "as_of"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT"), nullable=False
    )
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(10, 7))
    coverage: Mapped[Decimal] = mapped_column(Numeric(8, 7), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    confidence: Mapped[str] = mapped_column(String(24), nullable=False)
    config_version: Mapped[int] = mapped_column(nullable=False)
    config_snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    components: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    status_reason: Mapped[str | None] = mapped_column(String(1000))
