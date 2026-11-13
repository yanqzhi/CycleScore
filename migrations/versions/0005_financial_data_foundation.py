"""Add provider-neutral financial statements."""

import sqlalchemy as sa
from alembic import op

revision = "0005_financial_data_foundation"
down_revision = "0004_security_listing_normalization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "financial_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_code", sa.String(80), nullable=False),
        sa.Column("item_name", sa.String(200), nullable=False),
        sa.Column("statement_type", sa.String(2), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("unit_dimension", sa.String(24), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("item_code", name="uq_financial_items_item_code"),
        sa.CheckConstraint(
            "statement_type IN ('BS','PL','CF')",
            name="ck_financial_items_statement_type",
        ),
        sa.CheckConstraint(
            "unit_dimension IN ('CURRENCY_AMOUNT','PER_SHARE','SHARES',"
            "'PERCENTAGE','RATIO','COUNT')",
            name="ck_financial_items_unit_dimension",
        ),
    )
    op.create_table(
        "financial_statements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("statement_type", sa.String(2), nullable=False),
        sa.Column("accounting_standard", sa.String(40), nullable=False),
        sa.Column("consolidation_scope", sa.String(24), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_period", sa.String(4), nullable=False),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("publication_date", sa.Date(), nullable=False),
        sa.Column("publication_datetime", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("reporting_currency", sa.String(3), nullable=False),
        sa.Column("source_document_reference", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "statement_type IN ('BS','PL','CF')",
            name="ck_financial_statements_statement_type",
        ),
        sa.CheckConstraint(
            "consolidation_scope IN ('CONSOLIDATED','NON_CONSOLIDATED')",
            name="ck_financial_statements_consolidation_scope",
        ),
        sa.CheckConstraint(
            "revision_number >= 1", name="ck_financial_statements_revision_positive"
        ),
        sa.CheckConstraint(
            "period_start IS NULL OR period_start <= period_end",
            name="ck_financial_statements_period_range",
        ),
        sa.CheckConstraint(
            "statement_type = 'BS' OR period_start IS NOT NULL",
            name="ck_financial_statements_period_start_required",
        ),
    )
    op.create_index(
        "ix_financial_statements_company_period",
        "financial_statements",
        ["company_id", "period_end"],
    )
    op.create_index(
        "ix_financial_statements_company_type_period",
        "financial_statements",
        ["company_id", "statement_type", "period_end"],
    )
    op.create_index(
        "ix_financial_statements_source_period",
        "financial_statements",
        ["source_id", "period_end"],
    )
    op.create_index(
        "ix_financial_statements_available_at", "financial_statements", ["available_at"]
    )
    cols = [
        "company_id",
        "source_id",
        "statement_type",
        "accounting_standard",
        "consolidation_scope",
        "fiscal_year",
        "fiscal_period",
        "period_end",
        "revision_number",
    ]
    op.create_index(
        "uq_financial_statement_revision_instant",
        "financial_statements",
        cols,
        unique=True,
        sqlite_where=sa.text("period_start IS NULL"),
        postgresql_where=sa.text("period_start IS NULL"),
    )
    op.create_index(
        "uq_financial_statement_revision_period",
        "financial_statements",
        cols + ["period_start"],
        unique=True,
        sqlite_where=sa.text("period_start IS NOT NULL"),
        postgresql_where=sa.text("period_start IS NOT NULL"),
    )
    op.create_table(
        "financial_statement_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "financial_statement_id",
            sa.Integer(),
            sa.ForeignKey("financial_statements.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "financial_item_id",
            sa.Integer(),
            sa.ForeignKey("financial_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("value", sa.Numeric(38, 12), nullable=False),
        sa.Column("currency_code", sa.String(3)),
        sa.Column("unit_code", sa.String(24), nullable=False),
        sa.Column("scale_multiplier", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "financial_statement_id",
            "financial_item_id",
            name="uq_financial_statement_item",
        ),
        sa.CheckConstraint(
            "scale_multiplier >= 1", name="ck_financial_statement_items_scale_positive"
        ),
    )
    op.create_index(
        "ix_financial_statement_items_statement",
        "financial_statement_items",
        ["financial_statement_id", "financial_item_id"],
    )
    op.create_table(
        "financial_item_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_item_code", sa.String(120), nullable=False),
        sa.Column("source_item_name", sa.String(200), nullable=False),
        sa.Column(
            "financial_item_id",
            sa.Integer(),
            sa.ForeignKey("financial_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("accounting_standard", sa.String(40)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_financial_item_mapping_default",
        "financial_item_mappings",
        ["source_id", "source_item_code"],
        unique=True,
        sqlite_where=sa.text("accounting_standard IS NULL"),
        postgresql_where=sa.text("accounting_standard IS NULL"),
    )
    op.create_index(
        "uq_financial_item_mapping_standard",
        "financial_item_mappings",
        ["source_id", "source_item_code", "accounting_standard"],
        unique=True,
        sqlite_where=sa.text("accounting_standard IS NOT NULL"),
        postgresql_where=sa.text("accounting_standard IS NOT NULL"),
    )
    op.create_index(
        "ix_financial_item_mapping_code",
        "financial_item_mappings",
        ["source_id", "source_item_code"],
    )


def downgrade() -> None:
    op.drop_table("financial_item_mappings")
    op.drop_table("financial_statement_items")
    op.drop_table("financial_statements")
    op.drop_table("financial_items")
