"""Add append-only earnings Cycle Score snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0017_cycle_scores"
down_revision = "0016_value_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cycle_scores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id", ondelete="RESTRICT"),
        ),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Numeric(10, 7)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("phase", sa.String(24), nullable=False),
        sa.Column("phase_reason", sa.Text(), nullable=False),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("coverage", sa.Numeric(8, 7)),
        sa.Column("currency", sa.String(3)),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "normalized_earnings_result_id",
            sa.Integer(),
            sa.ForeignKey("normalized_earnings_results.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("calculation_version", sa.Integer(), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("input_references", sa.JSON(), nullable=False),
        sa.Column("status_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "score IS NULL OR score BETWEEN 0 AND 100",
            name="ck_cycle_scores_score_range",
        ),
        sa.CheckConstraint(
            "coverage IS NULL OR coverage BETWEEN 0 AND 1",
            name="ck_cycle_scores_coverage_range",
        ),
        sa.CheckConstraint(
            "calculation_version >= 1",
            name="ck_cycle_scores_calculation_version",
        ),
        sa.CheckConstraint(
            "status IN ('AVAILABLE','PARTIAL','INSUFFICIENT_DATA')",
            name="ck_cycle_scores_status",
        ),
        sa.CheckConstraint(
            "phase IN ('EARLY_RECOVERY','EXPANSION','PEAK','CONTRACTION','TROUGH',"
            "'UNKNOWN')",
            name="ck_cycle_scores_phase",
        ),
        sa.CheckConstraint(
            "confidence IN ('HIGH','MEDIUM','LOW','INSUFFICIENT')",
            name="ck_cycle_scores_confidence",
        ),
        sa.CheckConstraint(
            "(status = 'INSUFFICIENT_DATA' AND score IS NULL) OR "
            "(status IN ('AVAILABLE','PARTIAL') AND score IS NOT NULL)",
            name="ck_cycle_scores_status_score",
        ),
    )
    op.create_index(
        "ix_cycle_scores_company_asof", "cycle_scores", ["company_id", "as_of"]
    )
    op.create_index(
        "ix_cycle_scores_security_asof", "cycle_scores", ["security_id", "as_of"]
    )


def downgrade() -> None:
    op.drop_index("ix_cycle_scores_security_asof", table_name="cycle_scores")
    op.drop_index("ix_cycle_scores_company_asof", table_name="cycle_scores")
    op.drop_table("cycle_scores")
