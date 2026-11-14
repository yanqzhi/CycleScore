"""Add append-only Value Score snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0016_value_scores"
down_revision = "0015_valuation_percentiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "value_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Numeric(10, 7)),
        sa.Column("coverage", sa.Numeric(8, 7), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("confidence", sa.String(24), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("status_reason", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "score IS NULL OR score BETWEEN 0 AND 100", name="score_range"
        ),
        sa.CheckConstraint("coverage BETWEEN 0 AND 1", name="coverage_range"),
        sa.CheckConstraint("config_version >= 1", name="config_version"),
        sa.CheckConstraint(
            "(status = 'INSUFFICIENT_DATA' AND score IS NULL) OR "
            "(status IN ('AVAILABLE','PARTIAL') AND score IS NOT NULL)",
            name="status_score",
        ),
    )
    op.create_index(
        "ix_value_scores_security_asof", "value_scores", ["security_id", "as_of"]
    )


def downgrade() -> None:
    op.drop_index("ix_value_scores_security_asof", table_name="value_scores")
    op.drop_table("value_scores")
