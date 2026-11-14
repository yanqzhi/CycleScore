"""SQLAlchemy mappings for immutable quality assessments and anomaly events."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from cyclescope.infrastructure.database.base import Base, TimestampMixin


class DataQualityReportModel(TimestampMixin, Base):
    __tablename__ = "data_quality_reports"
    __table_args__ = (
        CheckConstraint("start_date <= end_date", name="quality_date_range"),
        CheckConstraint("available_records >= 0", name="quality_available_nonnegative"),
        CheckConstraint(
            "expected_sessions IS NULL OR expected_sessions >= 0",
            name="quality_expected_nonnegative",
        ),
        CheckConstraint(
            "score IS NULL OR score BETWEEN 0 AND 100", name="quality_score_range"
        ),
        CheckConstraint(
            "status IN ('PASS','WARNING','FAIL','INSUFFICIENT_DATA','NOT_APPLICABLE')",
            name="quality_status_valid",
        ),
        CheckConstraint(
            "calendar_status IN ('KNOWN','UNKNOWN_CALENDAR','NOT_APPLICABLE')",
            name="quality_calendar_status_valid",
        ),
        CheckConstraint(
            "(score IS NULL AND status IN ('INSUFFICIENT_DATA','NOT_APPLICABLE')) "
            "OR (score IS NOT NULL AND status IN ('PASS','WARNING','FAIL'))",
            name="quality_score_status_consistent",
        ),
        Index(
            "ix_quality_report_security_range", "security_id", "start_date", "end_date"
        ),
        Index("ix_quality_report_dataset_asof", "dataset_type", "as_of"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_type: Mapped[str] = mapped_column(String(24), nullable=False)
    security_id: Mapped[int | None] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT")
    )
    base_currency: Mapped[str | None] = mapped_column(String(3))
    quote_currency: Mapped[str | None] = mapped_column(String(3))
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT")
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_sessions: Mapped[int | None] = mapped_column(Integer)
    available_records: Mapped[int] = mapped_column(Integer, nullable=False)
    missing_sessions: Mapped[int | None] = mapped_column(Integer)
    first_available_date: Mapped[date | None] = mapped_column(Date)
    last_available_date: Mapped[date | None] = mapped_column(Date)
    coverage_ratio: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    score: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    config_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    calendar_status: Mapped[str] = mapped_column(String(24), nullable=False)
    components: Mapped[list[dict[str, str | None]]] = mapped_column(
        JSON, nullable=False
    )
    anomaly_counts: Mapped[list[dict[str, int | str]]] = mapped_column(
        JSON, nullable=False
    )
    config_snapshot: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)


class DataAnomalyModel(TimestampMixin, Base):
    __tablename__ = "data_anomalies"
    __table_args__ = (
        CheckConstraint(
            "revision_number IS NULL OR revision_number >= 1",
            name="anomaly_revision_positive",
        ),
        CheckConstraint(
            "severity IN ('INFO','WARNING','ERROR','CRITICAL')",
            name="anomaly_severity_valid",
        ),
        CheckConstraint(
            "status IN ('OPEN','ACKNOWLEDGED','RESOLVED','FALSE_POSITIVE')",
            name="anomaly_status_valid",
        ),
        CheckConstraint(
            "(status IN ('OPEN','ACKNOWLEDGED') AND resolved_at IS NULL) OR "
            "(status IN ('RESOLVED','FALSE_POSITIVE') AND resolved_at IS NOT NULL)",
            name="anomaly_resolution_consistent",
        ),
        Index("ix_data_anomalies_security_date", "security_id", "observation_date"),
        Index("ix_data_anomalies_dataset_source", "dataset_type", "source_id"),
        Index("ix_data_anomalies_severity_status", "severity", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    quality_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_quality_reports.id", ondelete="RESTRICT")
    )
    dataset_type: Mapped[str] = mapped_column(String(24), nullable=False)
    security_id: Mapped[int | None] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT")
    )
    base_currency: Mapped[str | None] = mapped_column(String(3))
    quote_currency: Mapped[str | None] = mapped_column(String(3))
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT")
    )
    revision_number: Mapped[int | None] = mapped_column(Integer)
    daily_price_id: Mapped[int | None] = mapped_column(
        ForeignKey("daily_prices.id", ondelete="RESTRICT")
    )
    fx_rate_id: Mapped[int | None] = mapped_column(
        ForeignKey("fx_rates.id", ondelete="RESTRICT")
    )
    anomaly_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    detected_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    expected_value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    detection_rule: Mapped[str] = mapped_column(String(64), nullable=False)
    detection_rule_version: Mapped[str] = mapped_column(String(32), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    version_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    __mapper_args__ = {"version_id_col": version_id}


class DataAnomalyLifecycleEventModel(Base):
    __tablename__ = "data_anomaly_lifecycle_events"
    __table_args__ = (
        CheckConstraint(
            "previous_status <> new_status", name="anomaly_event_status_changed"
        ),
        CheckConstraint(
            "previous_status IN ('OPEN','ACKNOWLEDGED','RESOLVED','FALSE_POSITIVE')",
            name="anomaly_event_previous_status_valid",
        ),
        CheckConstraint(
            "new_status IN ('OPEN','ACKNOWLEDGED','RESOLVED','FALSE_POSITIVE')",
            name="anomaly_event_new_status_valid",
        ),
        Index("ix_anomaly_lifecycle_anomaly_time", "anomaly_id", "transitioned_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    anomaly_id: Mapped[int] = mapped_column(
        ForeignKey("data_anomalies.id", ondelete="RESTRICT"), nullable=False
    )
    previous_status: Mapped[str] = mapped_column(String(20), nullable=False)
    new_status: Mapped[str] = mapped_column(String(20), nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    actor: Mapped[str | None] = mapped_column(String(255))
