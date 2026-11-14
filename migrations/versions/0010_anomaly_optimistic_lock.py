"""Add optimistic locking to anomaly lifecycle records."""

import sqlalchemy as sa
from alembic import op

revision = "0010_anomaly_optimistic_lock"
down_revision = "0009_anomaly_lifecycle_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "data_anomalies",
        sa.Column(
            "version_id", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("data_anomalies", "version_id")
