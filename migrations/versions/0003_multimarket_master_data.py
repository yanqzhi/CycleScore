"""Add exchange, identifier, listing, and exposure master adapters."""

import sqlalchemy as sa
from alembic import op

revision = "0003_multimarket_master_data"
down_revision = "0002_market_data"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Additive market-master tables while retaining existing security data."""
    op.create_table(
        "exchanges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("exchange_code", sa.String(32), nullable=False),
        sa.Column("exchange_name", sa.String(160), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("market_region", sa.String(40), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("currency_code", sa.String(3), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("exchange_code", name="uq_exchanges_exchange_code"),
    )
    op.create_table(
        "security_identifiers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("identifier_type", sa.String(40), nullable=False),
        sa.Column("identifier_value", sa.String(120), nullable=False),
        sa.Column(
            "exchange_id",
            sa.Integer(),
            sa.ForeignKey("exchanges.id", ondelete="RESTRICT"),
        ),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="ck_security_identifiers_identifier_validity_range",
        ),
    )
    op.create_index(
        "ix_security_identifiers_security_id", "security_identifiers", ["security_id"]
    )
    op.create_index(
        "ix_security_identifiers_scope",
        "security_identifiers",
        ["identifier_type", "identifier_value", "exchange_id"],
    )
    op.create_index(
        "uq_security_identifier_global_start",
        "security_identifiers",
        ["identifier_type", "identifier_value", "valid_from"],
        unique=True,
        sqlite_where=sa.text("exchange_id IS NULL"),
        postgresql_where=sa.text("exchange_id IS NULL"),
    )
    op.create_index(
        "uq_security_identifier_exchange_start",
        "security_identifiers",
        ["identifier_type", "identifier_value", "exchange_id", "valid_from"],
        unique=True,
        sqlite_where=sa.text("exchange_id IS NOT NULL"),
        postgresql_where=sa.text("exchange_id IS NOT NULL"),
    )

    op.create_table(
        "listings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "exchange_id",
            sa.Integer(),
            sa.ForeignKey("exchanges.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("trading_currency", sa.String(3), nullable=False),
        sa.Column("listing_date", sa.Date(), nullable=False),
        sa.Column("delisting_date", sa.Date()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "exchange_id",
            "ticker",
            "listing_date",
            name="uq_listing_exchange_ticker_start",
        ),
        sa.CheckConstraint(
            "delisting_date IS NULL OR delisting_date >= listing_date",
            name="ck_listings_listing_date_range",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'delisted')",
            name="ck_listings_listing_status",
        ),
        sa.CheckConstraint(
            "(status = 'delisted' AND delisting_date IS NOT NULL) OR "
            "(status != 'delisted' AND delisting_date IS NULL)",
            name="ck_listings_listing_status_date",
        ),
    )
    op.create_index("ix_listings_security_id", "listings", ["security_id"])
    op.create_index(
        "ix_listings_exchange_ticker", "listings", ["exchange_id", "ticker"]
    )
    op.create_table(
        "listing_status_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "listing_id",
            sa.Integer(),
            sa.ForeignKey("listings.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "listing_id", "effective_date", name="uq_listing_event_date"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'delisted')",
            name="ck_listing_status_events_status_event_status",
        ),
    )
    op.create_index(
        "ix_listing_status_events_listing_id", "listing_status_events", ["listing_id"]
    )


def downgrade() -> None:
    """Remove added structures; legacy security rows remain intact."""
    op.drop_index(
        "ix_listing_status_events_listing_id", table_name="listing_status_events"
    )
    op.drop_table("listing_status_events")
    op.drop_index("ix_listings_exchange_ticker", table_name="listings")
    op.drop_index("ix_listings_security_id", table_name="listings")
    op.drop_table("listings")
    op.drop_index("ix_security_identifiers_scope", table_name="security_identifiers")
    op.drop_index(
        "ix_security_identifiers_security_id", table_name="security_identifiers"
    )
    op.drop_table("security_identifiers")
    op.drop_table("exchanges")
