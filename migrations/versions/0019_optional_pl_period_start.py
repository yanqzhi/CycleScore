"""Allow PL statements without a reported period start."""

from alembic import op

revision = "0019_optional_pl_period_start"
down_revision = "0018_inventory_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("financial_statements") as batch_op:
        batch_op.drop_constraint(
            op.f(
                "ck_financial_statements_ck_financial_statements_period_start_required"
            ),
            type_="check",
        )
        batch_op.create_check_constraint(
            "period_start_required",
            "statement_type != 'CF' OR period_start IS NOT NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("financial_statements") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_financial_statements_period_start_required"), type_="check"
        )
        batch_op.create_check_constraint(
            op.f(
                "ck_financial_statements_ck_financial_statements_period_start_required"
            ),
            "statement_type = 'BS' OR period_start IS NOT NULL",
        )
