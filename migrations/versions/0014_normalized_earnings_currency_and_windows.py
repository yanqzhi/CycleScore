"""Record units, currency, D&A convention, and shared fiscal windows."""

import sqlalchemy as sa
from alembic import op

revision = "0014_normalized_earnings_currency_windows"
down_revision = "0013_normalized_earnings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "normalized_earnings_results",
        sa.Column("currency", sa.String(3), nullable=True),
    )
    op.add_column(
        "normalized_earnings_results",
        sa.Column(
            "unit",
            sa.String(24),
            nullable=False,
            server_default="CURRENCY_AMOUNT",
        ),
    )
    op.execute(
        "UPDATE normalized_earnings_results SET unit = 'PER_SHARE' WHERE metric = 'EPS'"
    )
    with op.batch_alter_table("normalized_earnings_results") as batch:
        batch.alter_column("unit", server_default=None)
        batch.add_column(sa.Column("window_start_fiscal_year", sa.Integer()))
        batch.add_column(sa.Column("window_end_fiscal_year", sa.Integer()))
        batch.add_column(
            sa.Column(
                "da_sign_convention",
                sa.String(24),
                nullable=False,
                server_default="UNKNOWN",
            )
        )
        batch.alter_column("da_sign_convention", server_default=None)
        batch.create_check_constraint(
            "ck_normalized_earnings_results_unit",
            "unit IN ('CURRENCY_AMOUNT','PER_SHARE')",
        )
        batch.create_check_constraint(
            "ck_normalized_earnings_results_currency_code",
            "currency IS NULL OR length(currency) = 3",
        )
        batch.create_check_constraint(
            "ck_normalized_earnings_results_da_sign_convention",
            "da_sign_convention IN ('UNKNOWN','POSITIVE_EXPENSE','NEGATIVE_EXPENSE')",
        )


def downgrade() -> None:
    with op.batch_alter_table("normalized_earnings_results") as batch:
        batch.drop_constraint(
            "ck_normalized_earnings_results_da_sign_convention", type_="check"
        )
        batch.drop_constraint(
            "ck_normalized_earnings_results_currency_code", type_="check"
        )
        batch.drop_constraint("ck_normalized_earnings_results_unit", type_="check")
        batch.drop_column("da_sign_convention")
        batch.drop_column("window_end_fiscal_year")
        batch.drop_column("window_start_fiscal_year")
        batch.drop_column("unit")
        batch.drop_column("currency")
