"""Persistence models for immutable raw acquisitions and ingestion runs."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from cyclescope.infrastructure.database.base import Base, TimestampMixin


class RawDataRecordModel(TimestampMixin, Base):
    __tablename__ = "raw_data_records"
    __table_args__ = (
        CheckConstraint("length(payload) > 0", name="payload_nonempty"),
        CheckConstraint("length(sha256) = 64", name="sha256_length"),
        Index("ix_raw_data_source_dataset", "source_id", "dataset_code"),
        Index("ix_raw_data_fetched_at", "fetched_at"),
        Index("ix_raw_data_sha256", "sha256"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    dataset_code: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    media_type: Mapped[str] = mapped_column(String(160), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    source_available_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    source_cursor: Mapped[str | None] = mapped_column(String(500))
    provider_request_id: Mapped[str | None] = mapped_column(String(200))


class IngestionRunModel(TimestampMixin, Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('RUNNING','SUCCEEDED','PARTIAL','FAILED')", name="status_valid"
        ),
        CheckConstraint(
            "(status = 'RUNNING' AND completed_at IS NULL) OR "
            "(status <> 'RUNNING' AND completed_at IS NOT NULL)",
            name="completion_status",
        ),
        CheckConstraint("fetched_count >= 0", name="fetched_nonnegative"),
        CheckConstraint("transformed_count >= 0", name="transformed_nonnegative"),
        CheckConstraint("accepted_count >= 0", name="accepted_nonnegative"),
        CheckConstraint("rejected_count >= 0", name="rejected_nonnegative"),
        CheckConstraint("duplicate_count >= 0", name="duplicate_nonnegative"),
        CheckConstraint(
            "accepted_count + rejected_count <= transformed_count",
            name="metrics_consistent",
        ),
        Index("ix_ingestion_runs_source_dataset", "source_id", "dataset_code"),
        Index("ix_ingestion_runs_status_started", "status", "started_at"),
        Index("ix_ingestion_runs_started_at", "started_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    dataset_code: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw_data_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("raw_data_records.id", ondelete="RESTRICT")
    )
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transformed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(String(2000))
