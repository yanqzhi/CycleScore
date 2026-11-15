"""Add versioned classification maps and hierarchical region masters."""

import sqlalchemy as sa
from alembic import op

revision = "0021_classification_and_region_masters"
down_revision = "0020_industry_signal_observations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classification_schemes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scheme_code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("publisher", sa.String(160), nullable=False),
        sa.Column("country_code", sa.String(2)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("scheme_code", name="uq_classification_scheme_code"),
        sa.CheckConstraint("length(trim(scheme_code)) > 0", name="scheme_code_valid"),
        sa.CheckConstraint("length(trim(name)) > 0", name="scheme_name_valid"),
        sa.CheckConstraint("length(trim(publisher)) > 0", name="publisher_valid"),
    )
    op.create_table(
        "classification_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "scheme_id",
            sa.Integer(),
            sa.ForeignKey("classification_schemes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_code", sa.String(64), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "scheme_id", "version_code", name="uq_classification_version_code"
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="version_effective_range",
        ),
        sa.CheckConstraint("length(trim(version_code)) > 0", name="version_code_valid"),
    )
    op.create_index(
        "ix_classification_versions_scheme_effective",
        "classification_versions",
        ["scheme_id", "effective_from", "effective_to"],
    )
    op.create_table(
        "industry_classification_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "classification_version_id",
            sa.Integer(),
            sa.ForeignKey("classification_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("external_code", sa.String(120), nullable=False),
        sa.Column("external_name", sa.String(240), nullable=False),
        sa.Column(
            "internal_industry_id",
            sa.Integer(),
            sa.ForeignKey("industries.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "internal_sub_industry_id",
            sa.Integer(),
            sa.ForeignKey("sub_industries.id", ondelete="RESTRICT"),
        ),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.Column("mapping_method", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4)),
        sa.Column("notes", sa.String(1000)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "classification_version_id",
            "external_code",
            "valid_from",
            name="uq_classification_mapping_valid_from",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from", name="mapping_validity_range"
        ),
        sa.CheckConstraint(
            "mapping_method IN ('EXACT','MANUAL','APPROXIMATE')",
            name="mapping_method",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="mapping_confidence_range",
        ),
        sa.CheckConstraint(
            "length(trim(external_code)) > 0", name="external_code_valid"
        ),
        sa.CheckConstraint(
            "length(trim(external_name)) > 0", name="external_name_valid"
        ),
    )
    op.create_index(
        "ix_classification_mapping_lookup",
        "industry_classification_mappings",
        ["classification_version_id", "external_code", "valid_from", "valid_to"],
    )
    op.create_index(
        "ix_classification_mapping_industry",
        "industry_classification_mappings",
        ["internal_industry_id"],
    )
    op.create_table(
        "regions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("region_code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("region_type", sa.String(24), nullable=False),
        sa.Column("country_code", sa.String(2)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("region_code", name="uq_region_code"),
        sa.CheckConstraint(
            "region_type IN ('GLOBAL','CONTINENT','COUNTRY','ECONOMIC_REGION',"
            "'MARKET_REGION','UNSPECIFIED')",
            name="region_type",
        ),
        sa.CheckConstraint("length(trim(region_code)) > 0", name="region_code_valid"),
        sa.CheckConstraint("length(trim(name)) > 0", name="region_name_valid"),
    )
    op.create_table(
        "region_relationships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "parent_region_id",
            sa.Integer(),
            sa.ForeignKey("regions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "child_region_id",
            sa.Integer(),
            sa.ForeignKey("regions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("relationship_type", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "parent_region_id",
            "child_region_id",
            "relationship_type",
            name="uq_region_relationship_edge",
        ),
        sa.CheckConstraint(
            "parent_region_id != child_region_id", name="region_not_self"
        ),
        sa.CheckConstraint(
            "relationship_type = 'CONTAINS'", name="region_relationship_type"
        ),
    )
    op.create_index(
        "ix_region_relationships_child", "region_relationships", ["child_region_id"]
    )
    op.create_index(
        "ix_region_relationships_parent",
        "region_relationships",
        ["parent_region_id"],
    )

    with op.batch_alter_table("industry_signal_observations") as batch_op:
        batch_op.add_column(sa.Column("classification_version_id", sa.Integer()))
        batch_op.add_column(sa.Column("classification_mapping_id", sa.Integer()))
        batch_op.create_foreign_key(
            op.f(
                "fk_industry_signal_observations_classification_version_id_classification_versions"
            ),
            "classification_versions",
            ["classification_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            op.f(
                "fk_industry_signal_observations_classification_mapping_id_industry_classification_mappings"
            ),
            "industry_classification_mappings",
            ["classification_mapping_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "classification_reference_pair",
            "(classification_version_id IS NULL AND classification_mapping_id IS NULL) "
            "OR (classification_version_id IS NOT NULL "
            "AND classification_mapping_id IS NOT NULL)",
        )
    op.create_index(
        "ix_industry_signals_classification_mapping",
        "industry_signal_observations",
        ["classification_mapping_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_industry_signals_classification_mapping",
        table_name="industry_signal_observations",
    )
    with op.batch_alter_table("industry_signal_observations") as batch_op:
        batch_op.drop_constraint(
            op.f("ck_industry_signal_observations_classification_reference_pair"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f(
                "fk_industry_signal_observations_classification_mapping_id_industry_classification_mappings"
            ),
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            op.f(
                "fk_industry_signal_observations_classification_version_id_classification_versions"
            ),
            type_="foreignkey",
        )
        batch_op.drop_column("classification_mapping_id")
        batch_op.drop_column("classification_version_id")
    op.drop_index("ix_region_relationships_parent", table_name="region_relationships")
    op.drop_index("ix_region_relationships_child", table_name="region_relationships")
    op.drop_table("region_relationships")
    op.drop_table("regions")
    op.drop_index(
        "ix_classification_mapping_industry",
        table_name="industry_classification_mappings",
    )
    op.drop_index(
        "ix_classification_mapping_lookup",
        table_name="industry_classification_mappings",
    )
    op.drop_table("industry_classification_mappings")
    op.drop_index(
        "ix_classification_versions_scheme_effective",
        table_name="classification_versions",
    )
    op.drop_table("classification_versions")
    op.drop_table("classification_schemes")
