"""Constrain standardized fiscal-period codes."""

from alembic import op

revision = "0006_financial_period_constraint"
down_revision = "0005_financial_data_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("financial_statements") as batch_op:
        batch_op.create_check_constraint(
            "fiscal_period",
            "fiscal_period IN ('FY','Q1','Q2','Q3','Q4','H1','9M','TTM')",
        )


def downgrade() -> None:
    with op.batch_alter_table("financial_statements") as batch_op:
        batch_op.drop_constraint("fiscal_period", type_="check")
