"""Distinguish economic/market membership from geographic containment."""

import sqlalchemy as sa
from alembic import op

revision = "0022_region_membership_relationships"
down_revision = "0021_classification_and_region_masters"
branch_labels = None
depends_on = None


_CONSTRAINT = "ck_region_relationships_region_relationship_type"


def upgrade() -> None:
    """Allow MEMBER_OF while preserving all existing relationship identities."""
    with op.batch_alter_table("region_relationships") as batch:
        batch.drop_constraint(op.f(_CONSTRAINT), type_="check")
        batch.create_check_constraint(
            "region_relationship_type",
            "relationship_type IN ('CONTAINS','MEMBER_OF')",
        )


def downgrade() -> None:
    """Restore the old contract only when no membership rows would be lost."""
    bind = op.get_bind()
    membership_count = bind.execute(
        sa.text(
            "SELECT count(*) FROM region_relationships "
            "WHERE relationship_type = 'MEMBER_OF'"
        )
    ).scalar_one()
    if membership_count:
        raise RuntimeError(
            "Cannot downgrade while MEMBER_OF relationships exist; "
            "remove or migrate them explicitly first."
        )
    with op.batch_alter_table("region_relationships") as batch:
        batch.drop_constraint(op.f(_CONSTRAINT), type_="check")
        batch.create_check_constraint(
            "region_relationship_type", "relationship_type = 'CONTAINS'"
        )
