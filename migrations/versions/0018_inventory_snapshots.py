"""Add append-only company-level inventory snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0018_inventory_snapshots"
down_revision = "0017_cycle_scores"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_snapshots",
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
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("closing_inventory", sa.Numeric(38, 12)),
        sa.Column("opening_inventory", sa.Numeric(38, 12)),
        sa.Column("average_inventory", sa.Numeric(38, 12)),
        sa.Column("cogs", sa.Numeric(38, 12)),
        sa.Column("inventory_change", sa.Numeric(38, 12)),
        sa.Column("inventory_growth", sa.Numeric(38, 12)),
        sa.Column("inventory_turnover", sa.Numeric(38, 12)),
        sa.Column("dio", sa.Numeric(38, 12)),
        sa.Column("trend", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("unavailable_reasons", sa.JSON(), nullable=False),
        sa.Column("data_coverage", sa.Numeric(8, 7), nullable=False),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("calculation_version", sa.Integer(), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("input_references", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("data_coverage BETWEEN 0 AND 1", name="coverage_range"),
        sa.CheckConstraint("calculation_version >= 1", name="calculation_version"),
        sa.CheckConstraint("fiscal_year >= 1", name="fiscal_year"),
        sa.CheckConstraint(
            "status IN ('AVAILABLE','PARTIAL','INSUFFICIENT_DATA','UNAVAILABLE')",
            name="status",
        ),
        sa.CheckConstraint(
            "trend IN ('INCREASING','DECREASING','STABLE','VOLATILE','UNKNOWN')",
            name="trend",
        ),
    )
    op.create_index(
        "ix_inventory_snapshots_company_asof",
        "inventory_snapshots",
        ["company_id", "as_of"],
    )
    op.create_index(
        "ix_inventory_snapshots_company_year",
        "inventory_snapshots",
        ["company_id", "fiscal_year", "as_of"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inventory_snapshots_company_year", table_name="inventory_snapshots"
    )
    op.drop_index(
        "ix_inventory_snapshots_company_asof", table_name="inventory_snapshots"
    )
    op.drop_table("inventory_snapshots")
