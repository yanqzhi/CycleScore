"""Persist immutable market-data quality reports and anomaly lifecycle events."""

import sqlalchemy as sa
from alembic import op

revision = "0008_market_data_quality"
down_revision = "0007_ingestion_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_quality_reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_type", sa.String(24), nullable=False),
        sa.Column(
            "security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id", ondelete="RESTRICT"),
        ),
        sa.Column("base_currency", sa.String(3)),
        sa.Column("quote_currency", sa.String(3)),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_sessions", sa.Integer()),
        sa.Column("available_records", sa.Integer(), nullable=False),
        sa.Column("missing_sessions", sa.Integer()),
        sa.Column("first_available_date", sa.Date()),
        sa.Column("last_available_date", sa.Date()),
        sa.Column("coverage_ratio", sa.Numeric(7, 4)),
        sa.Column("score", sa.Numeric(7, 4)),
        sa.Column("config_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("calendar_status", sa.String(24), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("anomaly_counts", sa.JSON(), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("start_date <= end_date", name="quality_date_range"),
        sa.CheckConstraint(
            "available_records >= 0", name="quality_available_nonnegative"
        ),
        sa.CheckConstraint(
            "expected_sessions IS NULL OR expected_sessions >= 0",
            name="quality_expected_nonnegative",
        ),
        sa.CheckConstraint(
            "score IS NULL OR score BETWEEN 0 AND 100", name="quality_score_range"
        ),
        sa.CheckConstraint(
            "calendar_status IN ('KNOWN','UNKNOWN_CALENDAR','NOT_APPLICABLE')",
            name="quality_calendar_status_valid",
        ),
        sa.CheckConstraint(
            "(score IS NULL AND status IN ('INSUFFICIENT_DATA','NOT_APPLICABLE')) "
            "OR (score IS NOT NULL AND status IN ('PASS','WARNING','FAIL'))",
            name="quality_score_status_consistent",
        ),
    )
    op.create_index(
        "ix_quality_report_security_range",
        "data_quality_reports",
        ["security_id", "start_date", "end_date"],
    )
    op.create_index(
        "ix_quality_report_dataset_asof",
        "data_quality_reports",
        ["dataset_type", "as_of"],
    )
    op.create_table(
        "data_anomalies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "quality_report_id",
            sa.Integer(),
            sa.ForeignKey("data_quality_reports.id", ondelete="RESTRICT"),
        ),
        sa.Column("dataset_type", sa.String(24), nullable=False),
        sa.Column(
            "security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id", ondelete="RESTRICT"),
        ),
        sa.Column("base_currency", sa.String(3)),
        sa.Column("quote_currency", sa.String(3)),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
        ),
        sa.Column("revision_number", sa.Integer()),
        sa.Column(
            "daily_price_id",
            sa.Integer(),
            sa.ForeignKey("daily_prices.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "fx_rate_id",
            sa.Integer(),
            sa.ForeignKey("fx_rates.id", ondelete="RESTRICT"),
        ),
        sa.Column("anomaly_type", sa.String(32), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("detected_value", sa.Numeric(38, 12)),
        sa.Column("expected_value", sa.Numeric(38, 12)),
        sa.Column("detection_rule", sa.String(64), nullable=False),
        sa.Column("detection_rule_version", sa.String(32), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision_number IS NULL OR revision_number >= 1",
            name="anomaly_revision_positive",
        ),
        sa.CheckConstraint(
            "severity IN ('INFO','WARNING','ERROR','CRITICAL')",
            name="anomaly_severity_valid",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','ACKNOWLEDGED','RESOLVED','FALSE_POSITIVE')",
            name="anomaly_status_valid",
        ),
        sa.CheckConstraint(
            "(status IN ('OPEN','ACKNOWLEDGED') AND resolved_at IS NULL) OR "
            "(status IN ('RESOLVED','FALSE_POSITIVE') AND resolved_at IS NOT NULL)",
            name="anomaly_resolution_consistent",
        ),
    )
    op.create_index(
        "ix_data_anomalies_security_date",
        "data_anomalies",
        ["security_id", "observation_date"],
    )
    op.create_index(
        "ix_data_anomalies_dataset_source",
        "data_anomalies",
        ["dataset_type", "source_id"],
    )
    op.create_index(
        "ix_data_anomalies_severity_status", "data_anomalies", ["severity", "status"]
    )


def downgrade() -> None:
    op.drop_index("ix_data_anomalies_severity_status", table_name="data_anomalies")
    op.drop_index("ix_data_anomalies_dataset_source", table_name="data_anomalies")
    op.drop_index("ix_data_anomalies_security_date", table_name="data_anomalies")
    op.drop_table("data_anomalies")
    op.drop_index("ix_quality_report_dataset_asof", table_name="data_quality_reports")
    op.drop_index("ix_quality_report_security_range", table_name="data_quality_reports")
    op.drop_table("data_quality_reports")
