"""Create valuation metric definitions and historical calculation results."""

import sqlalchemy as sa
from alembic import op

revision = "0012_valuation_data_foundation"
down_revision = "0011_market_data_access_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "valuation_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("metric_code", sa.String(40), nullable=False),
        sa.Column("metric_name", sa.String(160), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("unit", sa.String(24), nullable=False),
        sa.Column("currency_applicability", sa.String(24), nullable=False),
        sa.Column("required_inputs", sa.JSON(), nullable=False),
        sa.Column("calculation_method", sa.String(80), nullable=False),
        sa.Column("calculation_version", sa.Integer(), nullable=False),
        sa.Column("validity_rules", sa.JSON(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("metric_code", name="uq_valuation_metric_code"),
        sa.CheckConstraint(
            "unit IN ('RATIO','PER_SHARE','CURRENCY_AMOUNT')",
            name="ck_valuation_metrics_unit",
        ),
        sa.CheckConstraint(
            "currency_applicability IN ('NONE','MARKET_CURRENCY')",
            name="ck_valuation_metrics_currency_applicability",
        ),
        sa.CheckConstraint(
            "calculation_version >= 1",
            name="ck_valuation_metrics_version_positive",
        ),
    )
    op.create_table(
        "historical_valuation_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "metric_id",
            sa.Integer(),
            sa.ForeignKey("valuation_metrics.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("value", sa.Numeric(38, 12)),
        sa.Column("currency", sa.String(3)),
        sa.Column("unit", sa.String(24), nullable=False),
        sa.Column("financial_period", sa.String(128)),
        sa.Column("eps_calculation_method", sa.String(64)),
        sa.Column("calculation_version", sa.Integer(), nullable=False),
        sa.Column(
            "price_observation_id",
            sa.Integer(),
            sa.ForeignKey("daily_prices.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "price_source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
        ),
        sa.Column("price_revision_number", sa.Integer()),
        sa.Column("price_available_at", sa.DateTime(timezone=True)),
        sa.Column("financial_statement_ids", sa.JSON(), nullable=False),
        sa.Column("financial_source_ids", sa.JSON(), nullable=False),
        sa.Column("financial_statement_available_ats", sa.JSON(), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("unavailable_inputs", sa.JSON(), nullable=False),
        sa.Column("unavailable_reason", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('AVAILABLE','INSUFFICIENT_DATA','INVALID_INPUT',"
            "'NOT_APPLICABLE','UNAVAILABLE')",
            name="ck_historical_valuation_metrics_status",
        ),
        sa.CheckConstraint(
            "(status = 'AVAILABLE' AND value IS NOT NULL) OR "
            "(status <> 'AVAILABLE' AND value IS NULL)",
            name="ck_historical_valuation_metrics_status_value_consistency",
        ),
        sa.CheckConstraint(
            "calculation_version >= 1",
            name="ck_historical_valuation_metrics_version_positive",
        ),
    )
    op.create_index(
        "ix_historical_valuation_metric_security_date_asof",
        "historical_valuation_metrics",
        ["security_id", "metric_id", "observation_date", "as_of"],
    )
    op.create_table(
        "valuation_snapshot_inputs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.Integer(),
            sa.ForeignKey("historical_valuation_metrics.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("record_type", sa.String(24), nullable=False),
        sa.Column(
            "market_price_id",
            sa.Integer(),
            sa.ForeignKey("daily_prices.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "financial_statement_id",
            sa.Integer(),
            sa.ForeignKey("financial_statements.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "financial_statement_item_id",
            sa.Integer(),
            sa.ForeignKey("financial_statement_items.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_date", sa.Date()),
        sa.Column("financial_item_code", sa.String(80)),
        sa.Column("financial_period", sa.String(8)),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date()),
        sa.Column("publication_date", sa.Date()),
        sa.Column("publication_datetime", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(record_type = 'DAILY_PRICE' AND market_price_id IS NOT NULL "
            "AND financial_statement_id IS NULL "
            "AND financial_statement_item_id IS NULL) OR "
            "(record_type = 'FINANCIAL_LINE' AND market_price_id IS NULL "
            "AND financial_statement_id IS NOT NULL "
            "AND financial_statement_item_id IS NOT NULL)",
            name="ck_valuation_snapshot_inputs_record_reference_consistency",
        ),
        sa.CheckConstraint(
            "revision_number >= 1",
            name="ck_valuation_snapshot_inputs_revision_positive",
        ),
    )
    op.create_index(
        "ix_valuation_snapshot_inputs_snapshot",
        "valuation_snapshot_inputs",
        ["snapshot_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_valuation_snapshot_inputs_snapshot", table_name="valuation_snapshot_inputs"
    )
    op.drop_table("valuation_snapshot_inputs")
    op.drop_index(
        "ix_historical_valuation_metric_security_date_asof",
        table_name="historical_valuation_metrics",
    )
    op.drop_table("historical_valuation_metrics")
    op.drop_table("valuation_metrics")
