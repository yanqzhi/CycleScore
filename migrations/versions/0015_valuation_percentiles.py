"""Persist append-only historical valuation percentile results and audits."""

import sqlalchemy as sa
from alembic import op

revision = "0015_valuation_percentiles"
down_revision = "0014_normalized_earnings_currency_windows"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "valuation_percentile_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("security_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("lookback_period", sa.String(24), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_start", sa.Date()),
        sa.Column("observation_end", sa.Date()),
        sa.Column("current_value", sa.Numeric(38, 12)),
        sa.Column("percentile", sa.Numeric(10, 7)),
        sa.Column("historical_minimum", sa.Numeric(38, 12)),
        sa.Column("historical_maximum", sa.Numeric(38, 12)),
        sa.Column("historical_median", sa.Numeric(38, 12)),
        sa.Column("valid_observations", sa.Integer(), nullable=False),
        sa.Column("excluded_observations", sa.Integer(), nullable=False),
        sa.Column("expected_observations", sa.Integer()),
        sa.Column("coverage_ratio", sa.Numeric(8, 7)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("confidence", sa.String(24), nullable=False),
        sa.Column("data_quality", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(3)),
        sa.Column("unit", sa.String(24), nullable=False),
        sa.Column("financial_period", sa.String(128)),
        sa.Column("calculation_version", sa.Integer(), nullable=False),
        sa.Column("status_reason", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["security_id"], ["securities.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "metric IN ('PER','PBR','EV_EBITDA','NORMALIZED_PER',"
            "'NORMALIZED_EV_EBITDA')",
            name="metric",
        ),
        sa.CheckConstraint(
            "lookback_period IN ('3Y','5Y','10Y','AVAILABLE_HISTORY')", name="lookback"
        ),
        sa.CheckConstraint("method = 'ECDF'", name="method"),
        sa.CheckConstraint(
            "status IN ('AVAILABLE','INSUFFICIENT_DATA','INVALID_INPUT','UNAVAILABLE')",
            name="status",
        ),
        sa.CheckConstraint(
            "(status = 'AVAILABLE' AND percentile IS NOT NULL) OR "
            "(status <> 'AVAILABLE' AND percentile IS NULL)",
            name="status_value",
        ),
        sa.CheckConstraint(
            "percentile IS NULL OR percentile BETWEEN 0 AND 100",
            name="percentile_range",
        ),
        sa.CheckConstraint(
            "valid_observations >= 0 AND excluded_observations >= 0", name="counts"
        ),
        sa.CheckConstraint(
            "coverage_ratio IS NULL OR coverage_ratio BETWEEN 0 AND 1", name="coverage"
        ),
        sa.CheckConstraint("calculation_version >= 1", name="version"),
        sa.CheckConstraint("currency IS NULL OR length(currency) = 3", name="currency"),
        sa.CheckConstraint("unit = 'RATIO'", name="unit"),
    )
    op.create_index(
        "ix_valuation_percentile_security_asof",
        "valuation_percentile_results",
        ["security_id", "as_of"],
    )
    op.create_table(
        "valuation_percentile_inputs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("result_id", sa.Integer(), nullable=False),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(38, 12)),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(1000)),
        sa.Column("valuation_snapshot_id", sa.Integer()),
        sa.Column("normalized_earnings_result_id", sa.Integer()),
        sa.Column("market_source_id", sa.Integer()),
        sa.Column("financial_source_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["result_id"], ["valuation_percentile_results.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["valuation_snapshot_id"],
            ["historical_valuation_metrics.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["normalized_earnings_result_id"],
            ["normalized_earnings_results.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["market_source_id"], ["data_sources.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "valuation_snapshot_id IS NOT NULL OR "
            "normalized_earnings_result_id IS NOT NULL",
            name="at_least_one_parent",
        ),
    )
    op.create_index(
        "ix_valuation_percentile_inputs_result",
        "valuation_percentile_inputs",
        ["result_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_valuation_percentile_inputs_result",
        table_name="valuation_percentile_inputs",
    )
    op.drop_table("valuation_percentile_inputs")
    op.drop_index(
        "ix_valuation_percentile_security_asof",
        table_name="valuation_percentile_results",
    )
    op.drop_table("valuation_percentile_results")
