"""Persist immutable raw payloads and ingestion lifecycle metrics."""

import sqlalchemy as sa
from alembic import op

revision = "0007_ingestion_pipeline"
down_revision = "0006_financial_period_constraint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "raw_data_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("dataset_code", sa.String(100), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("media_type", sa.String(160), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_available_at", sa.DateTime(timezone=True)),
        sa.Column("source_cursor", sa.String(500)),
        sa.Column("provider_request_id", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(payload) > 0", name="ck_raw_data_records_payload_nonempty"
        ),
        sa.CheckConstraint(
            "length(sha256) = 64", name="ck_raw_data_records_sha256_length"
        ),
    )
    op.create_index(
        "ix_raw_data_source_dataset", "raw_data_records", ["source_id", "dataset_code"]
    )
    op.create_index("ix_raw_data_fetched_at", "raw_data_records", ["fetched_at"])
    op.create_index("ix_raw_data_sha256", "raw_data_records", ["sha256"])
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("dataset_code", sa.String(100), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "raw_data_record_id",
            sa.Integer(),
            sa.ForeignKey("raw_data_records.id", ondelete="RESTRICT"),
        ),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("transformed_count", sa.Integer(), nullable=False),
        sa.Column("accepted_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_message", sa.String(2000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('RUNNING','SUCCEEDED','PARTIAL','FAILED')",
            name="ck_ingestion_runs_status_valid",
        ),
        sa.CheckConstraint(
            "(status = 'RUNNING' AND completed_at IS NULL) OR "
            "(status <> 'RUNNING' AND completed_at IS NOT NULL)",
            name="ck_ingestion_runs_completion_status",
        ),
        sa.CheckConstraint(
            "fetched_count >= 0", name="ck_ingestion_runs_fetched_nonnegative"
        ),
        sa.CheckConstraint(
            "transformed_count >= 0", name="ck_ingestion_runs_transformed_nonnegative"
        ),
        sa.CheckConstraint(
            "accepted_count >= 0", name="ck_ingestion_runs_accepted_nonnegative"
        ),
        sa.CheckConstraint(
            "rejected_count >= 0", name="ck_ingestion_runs_rejected_nonnegative"
        ),
        sa.CheckConstraint(
            "duplicate_count >= 0", name="ck_ingestion_runs_duplicate_nonnegative"
        ),
        sa.CheckConstraint(
            "accepted_count + rejected_count <= transformed_count",
            name="ck_ingestion_runs_metrics_consistent",
        ),
    )
    op.create_index(
        "ix_ingestion_runs_source_dataset",
        "ingestion_runs",
        ["source_id", "dataset_code"],
    )
    op.create_index(
        "ix_ingestion_runs_status_started", "ingestion_runs", ["status", "started_at"]
    )
    op.create_index("ix_ingestion_runs_started_at", "ingestion_runs", ["started_at"])


def downgrade() -> None:
    op.drop_table("ingestion_runs")
    op.drop_table("raw_data_records")
