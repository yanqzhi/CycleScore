"""Persist append-only point-in-time industry signal aggregates."""

import sqlalchemy as sa
from alembic import op

revision = "0023_industry_signal_aggregates"
down_revision = "0022_region_membership_relationships"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "industry_signal_aggregates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "industry_id",
            sa.Integer(),
            sa.ForeignKey("industries.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "sub_industry_id",
            sa.Integer(),
            sa.ForeignKey("sub_industries.id", ondelete="RESTRICT"),
        ),
        sa.Column("signal_type", sa.String(32), nullable=False),
        sa.Column("temporal_kind", sa.String(12), nullable=False),
        sa.Column("aggregate_region_code", sa.String(64), nullable=False),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
        ),
        sa.Column("unit_code", sa.String(24), nullable=False),
        sa.Column("currency_code", sa.String(3)),
        sa.Column("observation_date", sa.Date()),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date()),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_code", sa.String(48), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("calculation_version", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("minimum_coverage", sa.Numeric(8, 7), nullable=False),
        sa.Column("value", sa.Numeric(38, 12)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("expected_contributor_count", sa.Integer()),
        sa.Column("actual_contributor_count", sa.Integer(), nullable=False),
        sa.Column("coverage_ratio", sa.Numeric(8, 7)),
        sa.Column("confidence", sa.Numeric(8, 7)),
        sa.Column("missing_reasons", sa.JSON(), nullable=False),
        sa.Column("validation_warnings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("industry_id > 0", name="aggregate_industry_positive"),
        sa.CheckConstraint(
            "sub_industry_id IS NULL OR sub_industry_id > 0",
            name="aggregate_sub_industry_positive",
        ),
        sa.CheckConstraint("policy_version >= 1", name="aggregate_policy_version"),
        sa.CheckConstraint(
            "calculation_version >= 1", name="aggregate_calculation_version"
        ),
        sa.CheckConstraint(
            "expected_contributor_count IS NULL OR expected_contributor_count > 0",
            name="aggregate_expected_count",
        ),
        sa.CheckConstraint(
            "actual_contributor_count >= 0", name="aggregate_actual_count"
        ),
        sa.CheckConstraint(
            "coverage_ratio IS NULL OR coverage_ratio BETWEEN 0 AND 1",
            name="aggregate_coverage_range",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="aggregate_confidence_range",
        ),
        sa.CheckConstraint(
            "minimum_coverage BETWEEN 0 AND 1", name="aggregate_minimum_coverage"
        ),
        sa.CheckConstraint(
            "status IN ('AVAILABLE','PARTIAL','INSUFFICIENT_DATA')",
            name="aggregate_status",
        ),
        sa.CheckConstraint(
            "operation IN ('SUM','CAPACITY_WEIGHTED_AVERAGE')",
            name="aggregate_operation",
        ),
        sa.CheckConstraint(
            "(status = 'INSUFFICIENT_DATA' AND value IS NULL) OR "
            "(status != 'INSUFFICIENT_DATA' AND value IS NOT NULL)",
            name="aggregate_value_status",
        ),
        sa.CheckConstraint(
            "(temporal_kind = 'PERIOD' AND observation_date IS NULL "
            "AND period_start IS NOT NULL AND period_end IS NOT NULL "
            "AND period_start <= period_end) OR "
            "(temporal_kind = 'POINT' AND observation_date IS NOT NULL "
            "AND period_start IS NULL AND period_end IS NULL)",
            name="aggregate_temporal_shape",
        ),
        sa.CheckConstraint(
            "(unit_code = 'CURRENCY' AND currency_code IS NOT NULL "
            "AND length(currency_code) = 3 AND upper(currency_code) = currency_code) "
            "OR (unit_code != 'CURRENCY' AND currency_code IS NULL)",
            name="aggregate_currency_unit",
        ),
    )
    op.create_index(
        "ix_industry_signal_aggregates_lookup",
        "industry_signal_aggregates",
        ["industry_id", "signal_type", "aggregate_region_code", "as_of"],
    )
    op.create_index(
        "ix_industry_signal_aggregates_source",
        "industry_signal_aggregates",
        ["source_id"],
    )
    op.create_table(
        "industry_signal_aggregate_contributors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "aggregate_id",
            sa.Integer(),
            sa.ForeignKey("industry_signal_aggregates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "observation_id",
            sa.Integer(),
            sa.ForeignKey("industry_signal_observations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("region_code", sa.String(64), nullable=False),
        sa.Column("observation_date", sa.Date()),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date()),
        sa.Column("publication_date", sa.Date(), nullable=False),
        sa.Column("publication_datetime", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_reference", sa.String(500)),
        sa.Column("input_role", sa.String(24), nullable=False),
        sa.Column("value", sa.Numeric(38, 12)),
        sa.Column("unit_code", sa.String(24), nullable=False),
        sa.Column("currency_code", sa.String(3)),
        sa.Column(
            "classification_version_id",
            sa.Integer(),
            sa.ForeignKey("classification_versions.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "classification_mapping_id",
            sa.Integer(),
            sa.ForeignKey("industry_classification_mappings.id", ondelete="RESTRICT"),
        ),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("calculation_weight", sa.Numeric(38, 12)),
        sa.Column("exclusion_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "aggregate_id",
            "observation_id",
            "input_role",
            name="uq_signal_aggregate_contributor_role",
        ),
        sa.CheckConstraint(
            "revision_number >= 1", name="contributor_revision_positive"
        ),
        sa.CheckConstraint(
            "input_role IN ('MEASURE','CAPACITY_WEIGHT')", name="contributor_role"
        ),
        sa.CheckConstraint(
            "(classification_version_id IS NULL AND classification_mapping_id IS NULL) "
            "OR (classification_version_id IS NOT NULL "
            "AND classification_mapping_id IS NOT NULL)",
            name="contributor_classification_pair",
        ),
        sa.CheckConstraint(
            "(included = 1 AND exclusion_reason IS NULL) OR "
            "(included = 0 AND exclusion_reason IS NOT NULL "
            "AND length(trim(exclusion_reason)) > 0)",
            name="contributor_inclusion_reason",
        ),
        sa.CheckConstraint(
            "calculation_weight IS NULL OR calculation_weight >= 0",
            name="contributor_weight_nonnegative",
        ),
    )
    op.create_index(
        "ix_signal_aggregate_contributors_observation",
        "industry_signal_aggregate_contributors",
        ["observation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_signal_aggregate_contributors_observation",
        table_name="industry_signal_aggregate_contributors",
    )
    op.drop_table("industry_signal_aggregate_contributors")
    op.drop_index(
        "ix_industry_signal_aggregates_source",
        table_name="industry_signal_aggregates",
    )
    op.drop_index(
        "ix_industry_signal_aggregates_lookup",
        table_name="industry_signal_aggregates",
    )
    op.drop_table("industry_signal_aggregates")
