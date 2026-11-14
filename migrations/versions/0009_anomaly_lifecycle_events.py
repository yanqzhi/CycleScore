"""Add append-only anomaly lifecycle audit events."""

import sqlalchemy as sa
from alembic import op

revision = "0009_anomaly_lifecycle_events"
down_revision = "0008_market_data_quality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "data_anomaly_lifecycle_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "anomaly_id",
            sa.Integer(),
            sa.ForeignKey("data_anomalies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("previous_status", sa.String(20), nullable=False),
        sa.Column("new_status", sa.String(20), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(255)),
        sa.CheckConstraint(
            "previous_status <> new_status", name="anomaly_event_status_changed"
        ),
        sa.CheckConstraint(
            "previous_status IN ('OPEN','ACKNOWLEDGED','RESOLVED','FALSE_POSITIVE')",
            name="anomaly_event_previous_status_valid",
        ),
        sa.CheckConstraint(
            "new_status IN ('OPEN','ACKNOWLEDGED','RESOLVED','FALSE_POSITIVE')",
            name="anomaly_event_new_status_valid",
        ),
    )
    op.create_index(
        "ix_anomaly_lifecycle_anomaly_time",
        "data_anomaly_lifecycle_events",
        ["anomaly_id", "transitioned_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_anomaly_lifecycle_anomaly_time",
        table_name="data_anomaly_lifecycle_events",
    )
    op.drop_table("data_anomaly_lifecycle_events")
