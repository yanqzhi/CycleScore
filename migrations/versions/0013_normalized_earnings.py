"""Add append-only normalized earnings results and input provenance."""

import sqlalchemy as sa
from alembic import op

revision = "0013_normalized_earnings"
down_revision = "0012_valuation_data_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "normalized_earnings_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Integer(),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "security_id",
            sa.Integer(),
            sa.ForeignKey("securities.id", ondelete="RESTRICT"),
        ),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("window_years", sa.Integer(), nullable=False),
        sa.Column("effective_window_years", sa.Integer(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("status_reason", sa.String(1000)),
        sa.Column("normalized_value", sa.Numeric(38, 12)),
        sa.Column("arithmetic_mean", sa.Numeric(38, 12)),
        sa.Column("median", sa.Numeric(38, 12)),
        sa.Column("minimum", sa.Numeric(38, 12)),
        sa.Column("maximum", sa.Numeric(38, 12)),
        sa.Column("standard_deviation", sa.Numeric(38, 12)),
        sa.Column("valid_fiscal_years", sa.Integer(), nullable=False),
        sa.Column("loss_making_years", sa.Integer(), nullable=False),
        sa.Column("data_coverage", sa.Numeric(8, 7), nullable=False),
        sa.Column("confidence", sa.String(16), nullable=False),
        sa.Column("calculation_period_start", sa.Date()),
        sa.Column("calculation_period_end", sa.Date()),
        sa.Column("fiscal_year_values", sa.JSON(), nullable=False),
        sa.Column("peak_candidate_year", sa.Integer()),
        sa.Column("trough_candidate_year", sa.Integer()),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("calculation_version", sa.Integer(), nullable=False),
        sa.Column("normalized_valuation_status", sa.String(24)),
        sa.Column("normalized_valuation_reason", sa.String(1000)),
        sa.Column("normalized_valuation_value", sa.Numeric(38, 12)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "window_years IN (5, 7, 10)",
            name="ck_normalized_earnings_results_window_years",
        ),
        sa.CheckConstraint(
            "effective_window_years >= 1",
            name="ck_normalized_earnings_results_effective_window",
        ),
        sa.CheckConstraint(
            "calculation_version >= 1",
            name="ck_normalized_earnings_results_version_positive",
        ),
        sa.CheckConstraint(
            "valid_fiscal_years >= 0", name="ck_normalized_earnings_results_valid_years"
        ),
        sa.CheckConstraint(
            "loss_making_years >= 0", name="ck_normalized_earnings_results_loss_years"
        ),
        sa.CheckConstraint(
            "metric IN ('OPERATING_PROFIT','NET_INCOME','EPS','EBITDA')",
            name="ck_normalized_earnings_results_metric",
        ),
        sa.CheckConstraint(
            "method IN ('ARITHMETIC_MEAN','MEDIAN')",
            name="ck_normalized_earnings_results_method",
        ),
        sa.CheckConstraint(
            "confidence IN ('HIGH','MEDIUM','LOW','INSUFFICIENT')",
            name="ck_normalized_earnings_results_confidence",
        ),
        sa.CheckConstraint(
            "data_coverage >= 0 AND data_coverage <= 1",
            name="ck_normalized_earnings_results_coverage",
        ),
        sa.CheckConstraint(
            "status IN ('AVAILABLE','INSUFFICIENT_DATA','UNAVAILABLE')",
            name="ck_normalized_earnings_results_status",
        ),
        sa.CheckConstraint(
            "(status = 'AVAILABLE' AND normalized_value IS NOT NULL) OR "
            "(status <> 'AVAILABLE' AND normalized_value IS NULL)",
            name="ck_normalized_earnings_results_status_value",
        ),
        sa.CheckConstraint(
            "normalized_valuation_status IS NULL OR normalized_valuation_status IN "
            "('AVAILABLE','INSUFFICIENT_DATA','INVALID_INPUT','NOT_APPLICABLE','UNAVAILABLE')",
            name="ck_normalized_earnings_results_normalized_valuation_status",
        ),
        sa.CheckConstraint(
            "(normalized_valuation_status = 'AVAILABLE' AND "
            "normalized_valuation_value IS NOT NULL) OR "
            "((normalized_valuation_status IS NULL OR "
            "normalized_valuation_status <> 'AVAILABLE') AND "
            "normalized_valuation_value IS NULL)",
            name="ck_normalized_earnings_results_normalized_valuation_status_value",
        ),
    )
    op.create_index(
        "ix_normalized_earnings_company_metric_asof",
        "normalized_earnings_results",
        ["company_id", "metric", "as_of"],
    )
    op.create_table(
        "normalized_earnings_input_refs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "result_id",
            sa.Integer(),
            sa.ForeignKey("normalized_earnings_results.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provenance_kind", sa.String(16), nullable=False),
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
        sa.Column("fiscal_year", sa.Integer()),
        sa.Column("fiscal_period", sa.String(8)),
        sa.Column("item_code", sa.String(80)),
        sa.Column("period_end", sa.Date()),
        sa.Column("observation_date", sa.Date()),
        sa.Column("financial_item_code", sa.String(80)),
        sa.Column("financial_period", sa.String(8)),
        sa.Column("period_start", sa.Date()),
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
            name="ck_normalized_earnings_input_refs_record_reference_consistency",
        ),
        sa.CheckConstraint(
            "revision_number >= 1",
            name="ck_normalized_earnings_input_refs_revision_positive",
        ),
        sa.CheckConstraint(
            "provenance_kind IN ('EARNINGS','VALUATION')",
            name="ck_normalized_earnings_input_refs_provenance_kind",
        ),
    )
    op.create_index(
        "ix_normalized_earnings_input_result",
        "normalized_earnings_input_refs",
        ["result_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_normalized_earnings_input_result",
        table_name="normalized_earnings_input_refs",
    )
    op.drop_table("normalized_earnings_input_refs")
    op.drop_index(
        "ix_normalized_earnings_company_metric_asof",
        table_name="normalized_earnings_results",
    )
    op.drop_table("normalized_earnings_results")
