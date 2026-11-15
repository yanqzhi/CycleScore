"""Create append-only provider-independent industry signal observations."""

import sqlalchemy as sa
from alembic import op

revision = "0020_industry_signal_observations"
down_revision = "0019_optional_pl_period_start"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "industry_signal_observations",
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
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("data_sources.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("signal_type", sa.String(32), nullable=False),
        sa.Column("temporal_kind", sa.String(12), nullable=False),
        sa.Column("region_code", sa.String(64), nullable=False),
        sa.Column("observation_date", sa.Date()),
        sa.Column("period_start", sa.Date()),
        sa.Column("period_end", sa.Date()),
        sa.Column("value", sa.Numeric(38, 12)),
        sa.Column("unit_code", sa.String(24), nullable=False),
        sa.Column("currency_code", sa.String(3)),
        sa.Column("publication_date", sa.Date(), nullable=False),
        sa.Column("publication_datetime", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("source_reference", sa.String(500)),
        sa.Column("missing_reason", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision_number >= 1", name="revision_positive"),
        sa.CheckConstraint(
            "signal_type IN ('INVENTORY','PRODUCTION','SHIPMENTS','SALES','ORDERS',"
            "'CAPACITY','CAPACITY_UTILIZATION','CAPACITY_ADDITION',"
            "'CAPACITY_CLOSURE_ANNOUNCED','CAPACITY_CLOSURE_COMPLETED')",
            name="signal_type",
        ),
        sa.CheckConstraint(
            "(temporal_kind = 'POINT' AND signal_type IN "
            "('INVENTORY','CAPACITY','CAPACITY_UTILIZATION')) OR "
            "(temporal_kind = 'PERIOD' AND signal_type IN "
            "('PRODUCTION','SHIPMENTS','SALES','ORDERS')) OR "
            "(temporal_kind = 'EVENT' AND signal_type IN "
            "('CAPACITY_ADDITION','CAPACITY_CLOSURE_ANNOUNCED',"
            "'CAPACITY_CLOSURE_COMPLETED'))",
            name="signal_temporal_compatibility",
        ),
        sa.CheckConstraint(
            "(temporal_kind IN ('POINT','EVENT') AND observation_date IS NOT NULL "
            "AND period_start IS NULL AND period_end IS NULL) OR "
            "(temporal_kind = 'PERIOD' AND observation_date IS NULL "
            "AND period_start IS NOT NULL AND period_end IS NOT NULL "
            "AND period_start <= period_end)",
            name="temporal_shape",
        ),
        sa.CheckConstraint(
            "unit_code IN ('TONNE','THOUSAND_TONNE','UNIT','THOUSAND_UNITS',"
            "'CURRENCY','PERCENTAGE','INDEX')",
            name="unit_code",
        ),
        sa.CheckConstraint(
            "(signal_type = 'CAPACITY_UTILIZATION' AND unit_code = 'PERCENTAGE') OR "
            "(signal_type IN ('INVENTORY','SALES','ORDERS') AND unit_code IN "
            "('TONNE','THOUSAND_TONNE','UNIT','THOUSAND_UNITS','CURRENCY','INDEX')) "
            "OR (signal_type IN ('PRODUCTION','SHIPMENTS','CAPACITY',"
            "'CAPACITY_ADDITION','CAPACITY_CLOSURE_ANNOUNCED',"
            "'CAPACITY_CLOSURE_COMPLETED') AND unit_code IN "
            "('TONNE','THOUSAND_TONNE','UNIT','THOUSAND_UNITS'))",
            name="unit_signal_compatibility",
        ),
        sa.CheckConstraint(
            "(unit_code = 'CURRENCY' AND currency_code IS NOT NULL "
            "AND length(currency_code) = 3 AND upper(currency_code) = currency_code) "
            "OR (unit_code != 'CURRENCY' AND currency_code IS NULL)",
            name="currency_unit_compatibility",
        ),
        sa.CheckConstraint(
            "(value IS NOT NULL AND missing_reason IS NULL) OR "
            "(value IS NULL AND missing_reason IS NOT NULL "
            "AND length(trim(missing_reason)) > 0)",
            name="missing_value_reason",
        ),
        sa.CheckConstraint(
            "publication_datetime IS NULL OR available_at >= publication_datetime",
            name="publication_availability_order",
        ),
        sa.CheckConstraint(
            "region_code = trim(region_code) AND length(region_code) BETWEEN 1 AND 64",
            name="region_code_valid",
        ),
    )
    op.create_index(
        "ix_industry_signals_industry_type_point_asof",
        "industry_signal_observations",
        ["industry_id", "signal_type", "observation_date", "available_at"],
    )
    op.create_index(
        "ix_industry_signals_industry_type_period_asof",
        "industry_signal_observations",
        ["industry_id", "signal_type", "period_end", "available_at"],
    )
    op.create_index(
        "ix_industry_signals_source_availability",
        "industry_signal_observations",
        ["source_id", "available_at"],
    )
    op.create_index(
        "ix_industry_signals_subindustry_region",
        "industry_signal_observations",
        ["sub_industry_id", "region_code"],
    )
    op.create_index(
        "uq_industry_signal_point_revision_no_subindustry",
        "industry_signal_observations",
        [
            "industry_id",
            "signal_type",
            "temporal_kind",
            "region_code",
            "observation_date",
            "source_id",
            "revision_number",
        ],
        unique=True,
        sqlite_where=sa.text(
            "sub_industry_id IS NULL AND temporal_kind IN ('POINT','EVENT')"
        ),
        postgresql_where=sa.text(
            "sub_industry_id IS NULL AND temporal_kind IN ('POINT','EVENT')"
        ),
    )
    op.create_index(
        "uq_industry_signal_point_revision_subindustry",
        "industry_signal_observations",
        [
            "industry_id",
            "sub_industry_id",
            "signal_type",
            "temporal_kind",
            "region_code",
            "observation_date",
            "source_id",
            "revision_number",
        ],
        unique=True,
        sqlite_where=sa.text(
            "sub_industry_id IS NOT NULL AND temporal_kind IN ('POINT','EVENT')"
        ),
        postgresql_where=sa.text(
            "sub_industry_id IS NOT NULL AND temporal_kind IN ('POINT','EVENT')"
        ),
    )
    op.create_index(
        "uq_industry_signal_period_revision_no_subindustry",
        "industry_signal_observations",
        [
            "industry_id",
            "signal_type",
            "temporal_kind",
            "region_code",
            "period_start",
            "period_end",
            "source_id",
            "revision_number",
        ],
        unique=True,
        sqlite_where=sa.text("sub_industry_id IS NULL AND temporal_kind = 'PERIOD'"),
        postgresql_where=sa.text(
            "sub_industry_id IS NULL AND temporal_kind = 'PERIOD'"
        ),
    )
    op.create_index(
        "uq_industry_signal_period_revision_subindustry",
        "industry_signal_observations",
        [
            "industry_id",
            "sub_industry_id",
            "signal_type",
            "temporal_kind",
            "region_code",
            "period_start",
            "period_end",
            "source_id",
            "revision_number",
        ],
        unique=True,
        sqlite_where=sa.text(
            "sub_industry_id IS NOT NULL AND temporal_kind = 'PERIOD'"
        ),
        postgresql_where=sa.text(
            "sub_industry_id IS NOT NULL AND temporal_kind = 'PERIOD'"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_industry_signal_period_revision_subindustry",
        table_name="industry_signal_observations",
    )
    op.drop_index(
        "uq_industry_signal_period_revision_no_subindustry",
        table_name="industry_signal_observations",
    )
    op.drop_index(
        "uq_industry_signal_point_revision_subindustry",
        table_name="industry_signal_observations",
    )
    op.drop_index(
        "uq_industry_signal_point_revision_no_subindustry",
        table_name="industry_signal_observations",
    )
    op.drop_index(
        "ix_industry_signals_subindustry_region",
        table_name="industry_signal_observations",
    )
    op.drop_index(
        "ix_industry_signals_source_availability",
        table_name="industry_signal_observations",
    )
    op.drop_index(
        "ix_industry_signals_industry_type_period_asof",
        table_name="industry_signal_observations",
    )
    op.drop_index(
        "ix_industry_signals_industry_type_point_asof",
        table_name="industry_signal_observations",
    )
    op.drop_table("industry_signal_observations")
