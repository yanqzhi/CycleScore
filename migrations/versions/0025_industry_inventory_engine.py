"""Persist append-only industry inventory cycle analysis."""

import sqlalchemy as sa
from alembic import op

revision = "0025_industry_inventory_engine"
down_revision = "0024_industry_signal_aggregate_scopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "industry_inventory_snapshots",
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
        sa.Column("aggregate_region_code", sa.String(64), nullable=False),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
        ),
        sa.Column("unit_code", sa.String(24), nullable=False),
        sa.Column("currency_code", sa.String(3)),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("classification", sa.String(32), nullable=False),
        sa.Column("trend", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        *[
            sa.Column(name, sa.Numeric(38, 12))
            for name in (
                "inventory_value",
                "prior_inventory_value",
                "absolute_change",
                "yoy_growth",
                "prior_yoy_growth",
                "growth_acceleration",
                "production_value",
                "shipments_value",
                "production_shipment_gap",
            )
        ],
        sa.Column("coverage", sa.Numeric(8, 7)),
        sa.Column("confidence", sa.Numeric(8, 7)),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("unavailable_reasons", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "industry_id > 0", name="industry_inventory_industry_positive"
        ),
        sa.CheckConstraint(
            "config_version > 0", name="industry_inventory_config_version"
        ),
        sa.CheckConstraint(
            "coverage IS NULL OR coverage BETWEEN 0 AND 1",
            name="industry_inventory_coverage",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="industry_inventory_confidence",
        ),
        sa.CheckConstraint(
            "status IN ('AVAILABLE','PARTIAL','INSUFFICIENT_DATA')",
            name="industry_inventory_status",
        ),
        sa.CheckConstraint(
            "trend IN ('INCREASING','DECREASING','STABLE','UNKNOWN')",
            name="industry_inventory_trend",
        ),
    )
    op.create_index(
        "ix_industry_inventory_lookup",
        "industry_inventory_snapshots",
        ["industry_id", "aggregate_region_code", "as_of"],
    )
    op.create_table(
        "industry_inventory_scopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.Integer(),
            sa.ForeignKey("industry_inventory_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "region_id",
            sa.Integer(),
            sa.ForeignKey("regions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("region_code", sa.String(64), nullable=False),
        sa.Column("scope_role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "snapshot_id", "region_id", "scope_role", name="uq_industry_inventory_scope"
        ),
        sa.CheckConstraint(
            "scope_role IN ('REQUESTED','CONTRIBUTING')",
            name="industry_inventory_scope_role",
        ),
    )
    op.create_index(
        "ix_industry_inventory_scopes_order",
        "industry_inventory_scopes",
        ["snapshot_id", "scope_role", "region_code", "region_id"],
    )
    op.create_table(
        "industry_inventory_inputs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.Integer(),
            sa.ForeignKey("industry_inventory_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "aggregate_id",
            sa.Integer(),
            sa.ForeignKey("industry_signal_aggregates.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("observation_date", sa.Date()),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date()),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
        ),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("contributor_revisions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "snapshot_id", "aggregate_id", "role", name="uq_industry_inventory_input"
        ),
        sa.CheckConstraint(
            "role IN ('CURRENT_INVENTORY','PRIOR_INVENTORY','YEAR_PRIOR_INVENTORY',"
            "'PRIOR_YEAR_PRIOR_INVENTORY','PRODUCTION','SHIPMENTS')",
            name="industry_inventory_input_role",
        ),
    )
    op.create_index(
        "ix_industry_inventory_inputs_aggregate",
        "industry_inventory_inputs",
        ["aggregate_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_industry_inventory_inputs_aggregate", table_name="industry_inventory_inputs"
    )
    op.drop_table("industry_inventory_inputs")
    op.drop_index(
        "ix_industry_inventory_scopes_order",
        table_name="industry_inventory_scopes",
    )
    op.drop_table("industry_inventory_scopes")
    op.drop_index(
        "ix_industry_inventory_lookup", table_name="industry_inventory_snapshots"
    )
    op.drop_table("industry_inventory_snapshots")
