"""Persist aggregate scope identities without inferring old constituents."""

import sqlalchemy as sa
from alembic import op

revision = "0024_industry_signal_aggregate_scopes"
down_revision = "0023_industry_signal_aggregates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("industry_signal_aggregates") as batch_op:
        batch_op.add_column(
            sa.Column(
                "aggregate_region_id",
                sa.Integer(),
                sa.ForeignKey("regions.id", ondelete="RESTRICT"),
                nullable=True,
            )
        )
        batch_op.create_check_constraint(
            "aggregate_complete_scope_identity",
            "scope_complete = 0 OR aggregate_region_id IS NOT NULL",
        )
        batch_op.add_column(
            sa.Column(
                "scope_complete",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    op.create_table(
        "industry_signal_aggregate_scopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "aggregate_id",
            sa.Integer(),
            sa.ForeignKey("industry_signal_aggregates.id", ondelete="RESTRICT"),
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
            "aggregate_id", "region_id", "scope_role", name="uq_signal_aggregate_scope"
        ),
        sa.CheckConstraint(
            "scope_role IN ('AGGREGATE','CONSTITUENT')", name="aggregate_scope_role"
        ),
    )
    op.create_index(
        "ix_signal_aggregate_scopes_order",
        "industry_signal_aggregate_scopes",
        ["aggregate_id", "scope_role", "region_code", "region_id"],
    )
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE industry_signal_aggregates SET aggregate_region_id = "
            "(SELECT regions.id FROM regions WHERE "
            "regions.region_code = industry_signal_aggregates.aggregate_region_code) "
            "WHERE EXISTS (SELECT 1 FROM regions WHERE "
            "regions.region_code = industry_signal_aggregates.aggregate_region_code)"
        )
    )
    # Existing snapshots never stored their constituents. Backfill only their
    # known aggregate identity; scope_complete remains false for those records.
    connection.execute(
        sa.text(
            "INSERT INTO industry_signal_aggregate_scopes "
            "(aggregate_id, region_id, region_code, scope_role, created_at, "
            "updated_at) "
            "SELECT aggregates.id, regions.id, regions.region_code, 'AGGREGATE', "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "FROM industry_signal_aggregates AS aggregates "
            "JOIN regions ON regions.id = aggregates.aggregate_region_id"
        )
    )


def downgrade() -> None:
    op.drop_index(
        "ix_signal_aggregate_scopes_order",
        table_name="industry_signal_aggregate_scopes",
    )
    op.drop_table("industry_signal_aggregate_scopes")
    with op.batch_alter_table("industry_signal_aggregates") as batch_op:
        batch_op.drop_constraint("aggregate_complete_scope_identity", type_="check")
        batch_op.drop_column("scope_complete")
        batch_op.drop_column("aggregate_region_id")
