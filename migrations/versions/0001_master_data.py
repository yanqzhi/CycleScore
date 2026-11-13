"""Create initial CycleScope master-data schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001_master_data"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create master-data tables and constraints."""
    op.create_table(
        "industries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code", name="uq_industries_code"),
    )
    op.create_table(
        "data_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("provider_type", sa.String(40), nullable=False),
        sa.Column("website", sa.String(500)),
        sa.Column("licensing_type", sa.String(80)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("code", name="uq_data_sources_code"),
    )
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("fiscal_year_end", sa.String(5)),
        sa.Column("reporting_currency", sa.String(3)),
        sa.Column("listing_status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_companies_country_code", "companies", ["country_code"])
    op.create_table(
        "sub_industries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "industry_id",
            sa.Integer(),
            sa.ForeignKey("industries.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "industry_id", "code", name="uq_sub_industries_industry_id"
        ),
    )
    op.create_index("ix_sub_industries_industry_id", "sub_industries", ["industry_id"])
    op.create_table(
        "securities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(32), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("security_type", sa.String(32), nullable=False),
        sa.Column("listing_date", sa.Date()),
        sa.Column("delisting_date", sa.Date()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("exchange", "ticker", name="uq_securities_exchange_ticker"),
    )
    op.create_index("ix_securities_company_id", "securities", ["company_id"])
    op.create_table(
        "company_industry_exposures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "sub_industry_id",
            sa.Integer(),
            sa.ForeignKey("sub_industries.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revenue_share", sa.Numeric(8, 7), nullable=False),
        sa.Column("valid_from", sa.Date()),
        sa.Column("valid_to", sa.Date()),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revenue_share >= 0 AND revenue_share <= 1",
            name="ck_company_industry_exposures_revenue_share_range",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="ck_company_industry_exposures_validity_range",
        ),
    )
    op.create_index(
        "ix_company_industry_exposures_company_id",
        "company_industry_exposures",
        ["company_id"],
    )
    op.create_index(
        "ix_company_industry_exposures_sub_industry_id",
        "company_industry_exposures",
        ["sub_industry_id"],
    )


def downgrade() -> None:
    """Drop the initial master-data schema."""
    op.drop_index(
        "ix_company_industry_exposures_sub_industry_id",
        table_name="company_industry_exposures",
    )
    op.drop_index(
        "ix_company_industry_exposures_company_id",
        table_name="company_industry_exposures",
    )
    op.drop_table("company_industry_exposures")
    op.drop_index("ix_securities_company_id", table_name="securities")
    op.drop_table("securities")
    op.drop_index("ix_sub_industries_industry_id", table_name="sub_industries")
    op.drop_table("sub_industries")
    op.drop_index("ix_companies_country_code", table_name="companies")
    op.drop_table("companies")
    op.drop_table("data_sources")
    op.drop_table("industries")
