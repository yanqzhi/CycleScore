"""Add append-only Industry Supply & Demand analysis tables."""

import sqlalchemy as sa
from alembic import op

revision = "0027_industry_supply_demand_engine"
down_revision = "0026_industry_inventory_input_composition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "industry_supply_demand_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("industry_id", sa.Integer(), nullable=False),
        sa.Column("sub_industry_id", sa.Integer(), nullable=True),
        sa.Column("aggregate_region_id", sa.Integer(), nullable=True),
        sa.Column("aggregate_region_code", sa.String(length=64), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("unit_code", sa.String(length=24), nullable=True),
        sa.Column("currency_code", sa.String(length=3), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("observation_date", sa.Date(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("phase", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("production_value", sa.Numeric(38, 12), nullable=True),
        sa.Column("shipments_value", sa.Numeric(38, 12), nullable=True),
        sa.Column("flow_gap", sa.Numeric(38, 12), nullable=True),
        sa.Column("flow_gap_ratio", sa.Numeric(38, 12), nullable=True),
        sa.Column("shipment_growth_yoy", sa.Numeric(38, 12), nullable=True),
        sa.Column("inventory_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("inventory_classification", sa.String(length=32), nullable=True),
        sa.Column("inventory_trend", sa.String(length=16), nullable=True),
        sa.Column("inventory_yoy_growth", sa.Numeric(38, 12), nullable=True),
        sa.Column("inventory_growth_acceleration", sa.Numeric(38, 12), nullable=True),
        sa.Column("inventory_coverage", sa.Numeric(8, 7), nullable=True),
        sa.Column("inventory_confidence", sa.Numeric(8, 7), nullable=True),
        sa.Column("coverage", sa.Numeric(8, 7), nullable=True),
        sa.Column("evidence_coverage", sa.Numeric(8, 7), nullable=False),
        sa.Column("confidence", sa.Numeric(8, 7), nullable=True),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("unavailable_reasons", sa.JSON(), nullable=False),
        sa.Column("validation_warnings", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("industry_id > 0", name="supply_demand_industry_positive"),
        sa.CheckConstraint("config_version > 0", name="supply_demand_config_version"),
        sa.CheckConstraint(
            "coverage IS NULL OR coverage BETWEEN 0 AND 1",
            name="supply_demand_coverage",
        ),
        sa.CheckConstraint(
            "evidence_coverage BETWEEN 0 AND 1",
            name="supply_demand_evidence_coverage",
        ),
        sa.CheckConstraint(
            "inventory_coverage IS NULL OR inventory_coverage BETWEEN 0 AND 1",
            name="supply_demand_inventory_coverage",
        ),
        sa.CheckConstraint(
            "inventory_confidence IS NULL OR inventory_confidence BETWEEN 0 AND 1",
            name="supply_demand_inventory_confidence",
        ),
        sa.CheckConstraint(
            "confidence IS NULL", name="supply_demand_v1_confidence_unknown"
        ),
        sa.CheckConstraint(
            "status IN ('AVAILABLE','PARTIAL','INSUFFICIENT_DATA')",
            name="supply_demand_status",
        ),
        sa.CheckConstraint(
            "phase IN ('DEMAND_RECOVERY','EXPANSION','BALANCED','OVERSUPPLY',"
            "'DEMAND_SLOWDOWN','UNDERSUPPLY','UNKNOWN')",
            name="supply_demand_phase",
        ),
        sa.ForeignKeyConstraint(
            ["industry_id"], ["industries.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["sub_industry_id"], ["sub_industries.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["aggregate_region_id"], ["regions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["data_sources.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["inventory_snapshot_id"],
            ["industry_inventory_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_industry_supply_demand_lookup",
        "industry_supply_demand_snapshots",
        ["industry_id", "aggregate_region_code", "as_of"],
    )
    op.create_table(
        "industry_supply_demand_inputs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("aggregate_id", sa.Integer(), nullable=True),
        sa.Column("inventory_snapshot_id", sa.Integer(), nullable=True),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("unit_code", sa.String(length=24), nullable=True),
        sa.Column("currency_code", sa.String(length=3), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("contributing_regions", sa.JSON(), nullable=False),
        sa.Column("coverage", sa.Numeric(8, 7), nullable=True),
        sa.Column("policy_code", sa.String(length=48), nullable=True),
        sa.Column("policy_version", sa.Integer(), nullable=True),
        sa.Column("calculation_version", sa.Integer(), nullable=True),
        sa.Column("classification_references", sa.JSON(), nullable=False),
        sa.Column("contributor_revisions", sa.JSON(), nullable=False),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(aggregate_id IS NOT NULL AND inventory_snapshot_id IS NULL) OR "
            "(aggregate_id IS NULL AND inventory_snapshot_id IS NOT NULL)",
            name="supply_demand_input_exactly_one_source",
        ),
        sa.CheckConstraint(
            "coverage IS NULL OR coverage BETWEEN 0 AND 1",
            name="supply_demand_input_coverage",
        ),
        sa.CheckConstraint(
            "(included = 1 AND exclusion_reason IS NULL) OR "
            "(included = 0 AND exclusion_reason IS NOT NULL "
            "AND length(trim(exclusion_reason)) > 0)",
            name="supply_demand_input_inclusion_reason",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["industry_supply_demand_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["aggregate_id"], ["industry_signal_aggregates.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["inventory_snapshot_id"],
            ["industry_inventory_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["data_sources.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "aggregate_id",
            "inventory_snapshot_id",
            "role",
            name="uq_industry_supply_demand_input",
        ),
    )
    op.create_index(
        "ix_industry_supply_demand_inputs_aggregate",
        "industry_supply_demand_inputs",
        ["aggregate_id"],
    )
    op.create_table(
        "industry_supply_demand_scopes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("region_code", sa.String(length=64), nullable=False),
        sa.Column("scope_role", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "scope_role IN ('REQUESTED','CONTRIBUTING')",
            name="supply_demand_scope_role",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["industry_supply_demand_snapshots.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["region_id"], ["regions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "snapshot_id",
            "region_id",
            "scope_role",
            name="uq_industry_supply_demand_scope",
        ),
    )
    op.create_index(
        "ix_industry_supply_demand_scopes_order",
        "industry_supply_demand_scopes",
        ["snapshot_id", "scope_role", "region_code", "region_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_industry_supply_demand_scopes_order",
        table_name="industry_supply_demand_scopes",
    )
    op.drop_table("industry_supply_demand_scopes")
    op.drop_index(
        "ix_industry_supply_demand_inputs_aggregate",
        table_name="industry_supply_demand_inputs",
    )
    op.drop_table("industry_supply_demand_inputs")
    op.drop_index(
        "ix_industry_supply_demand_lookup",
        table_name="industry_supply_demand_snapshots",
    )
    op.drop_table("industry_supply_demand_snapshots")
