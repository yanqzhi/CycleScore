"""Add point-in-time daily prices and FX rates."""

import sqlalchemy as sa
from alembic import op

revision = "0002_market_data"
down_revision = "0001_master_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create append-only market data tables."""
    op.create_table(
        "daily_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(20, 8), nullable=False),
        sa.Column("high", sa.Numeric(20, 8), nullable=False),
        sa.Column("low", sa.Numeric(20, 8), nullable=False),
        sa.Column("close", sa.Numeric(20, 8), nullable=False),
        sa.Column("adjusted_close", sa.Numeric(20, 8)),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("publication_date", sa.Date()),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "security_id",
            "observation_date",
            "source_id",
            "revision_number",
            name="uq_daily_prices_observation_revision",
        ),
        sa.CheckConstraint(
            "open >= 0 AND high >= 0 AND low >= 0 AND close >= 0",
            name="ck_daily_prices_price_values_nonnegative",
        ),
        sa.CheckConstraint(
            "adjusted_close IS NULL OR adjusted_close >= 0",
            name="ck_daily_prices_adjusted_close_nonnegative",
        ),
        sa.CheckConstraint(
            "high >= open AND high >= close AND high >= low",
            name="ck_daily_prices_high_relationship",
        ),
        sa.CheckConstraint(
            "low <= open AND low <= close",
            name="ck_daily_prices_low_relationship",
        ),
        sa.CheckConstraint("volume >= 0", name="ck_daily_prices_volume_nonnegative"),
        sa.CheckConstraint(
            "revision_number >= 1", name="ck_daily_prices_revision_positive"
        ),
    )
    op.create_index(
        "ix_daily_prices_security_date",
        "daily_prices",
        ["security_id", "observation_date"],
    )
    op.create_index(
        "ix_daily_prices_observation_date", "daily_prices", ["observation_date"]
    )
    op.create_table(
        "fx_rates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("base_currency", sa.String(3), nullable=False),
        sa.Column("quote_currency", sa.String(3), nullable=False),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("rate", sa.Numeric(24, 12), nullable=False),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("publication_date", sa.Date()),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "base_currency",
            "quote_currency",
            "observation_date",
            "source_id",
            "revision_number",
            name="uq_fx_rates_observation_revision",
        ),
        sa.CheckConstraint(
            "base_currency <> quote_currency",
            name="ck_fx_rates_currency_pair_distinct",
        ),
        sa.CheckConstraint("rate > 0", name="ck_fx_rates_rate_positive"),
        sa.CheckConstraint(
            "revision_number >= 1", name="ck_fx_rates_revision_positive"
        ),
    )
    op.create_index(
        "ix_fx_rates_pair_date",
        "fx_rates",
        ["base_currency", "quote_currency", "observation_date"],
    )


def downgrade() -> None:
    """Drop market-data tables while preserving master data."""
    op.drop_index("ix_fx_rates_pair_date", table_name="fx_rates")
    op.drop_table("fx_rates")
    op.drop_index("ix_daily_prices_observation_date", table_name="daily_prices")
    op.drop_index("ix_daily_prices_security_date", table_name="daily_prices")
    op.drop_table("daily_prices")
