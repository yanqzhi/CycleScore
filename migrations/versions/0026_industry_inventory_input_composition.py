"""Persist actual regional composition and coverage per inventory input."""

import sqlalchemy as sa
from alembic import op

revision = "0026_industry_inventory_input_composition"
down_revision = "0025_industry_inventory_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "industry_inventory_inputs",
        sa.Column("contributing_regions", sa.JSON(), nullable=True),
    )
    op.add_column(
        "industry_inventory_inputs",
        sa.Column(
            "included",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "industry_inventory_inputs",
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "industry_inventory_inputs",
        sa.Column("coverage", sa.Numeric(8, 7), nullable=True),
    )
    with op.batch_alter_table("industry_inventory_inputs") as batch_op:
        batch_op.create_check_constraint(
            "industry_inventory_input_inclusion_reason",
            "(included = 1 AND exclusion_reason IS NULL) OR "
            "(included = 0 AND exclusion_reason IS NOT NULL "
            "AND length(trim(exclusion_reason)) > 0)",
        )


def downgrade() -> None:
    with op.batch_alter_table("industry_inventory_inputs") as batch_op:
        batch_op.drop_constraint(
            "industry_inventory_input_inclusion_reason", type_="check"
        )
    op.drop_column("industry_inventory_inputs", "exclusion_reason")
    op.drop_column("industry_inventory_inputs", "included")
    op.drop_column("industry_inventory_inputs", "coverage")
    op.drop_column("industry_inventory_inputs", "contributing_regions")
