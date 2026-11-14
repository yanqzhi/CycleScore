"""Index source-scoped point-in-time market-data reads."""

from alembic import op

revision = "0011_market_data_access_indexes"
down_revision = "0010_anomaly_optimistic_lock"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_daily_prices_security_source_date_asof_revision",
        "daily_prices",
        [
            "security_id",
            "source_id",
            "observation_date",
            "available_at",
            "revision_number",
        ],
    )
    op.create_index(
        "ix_fx_rates_pair_source_date_asof_revision",
        "fx_rates",
        [
            "base_currency",
            "quote_currency",
            "source_id",
            "observation_date",
            "available_at",
            "revision_number",
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_fx_rates_pair_source_date_asof_revision", table_name="fx_rates")
    op.drop_index(
        "ix_daily_prices_security_source_date_asof_revision",
        table_name="daily_prices",
    )
