"""SQLite persistence tests for classification and region reference masters."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cyclescope.application.dto.classification import (
    CreateClassificationSchemeRequest,
    CreateClassificationVersionRequest,
    CreateIndustryClassificationMappingRequest,
    ResolveIndustryClassificationRequest,
)
from cyclescope.application.dto.industry_signal import (
    ImportIndustrySignalsRequest,
    IndustrySignalInput,
)
from cyclescope.application.dto.region import (
    CreateRegionRelationshipRequest,
    CreateRegionRequest,
    GetRegionHierarchyRequest,
)
from cyclescope.application.use_cases.classification_master import (
    RegisterClassificationScheme,
    RegisterClassificationVersion,
    RegisterIndustryClassificationMapping,
    ResolveIndustryClassification,
)
from cyclescope.application.use_cases.industry_signals import ImportIndustrySignals
from cyclescope.application.use_cases.region_master import (
    GetRegionAncestorPaths,
    GetRegionDescendants,
    GetRegionMembers,
    GetRegionMemberships,
    RegisterRegion,
    RegisterRegionRelationship,
)
from cyclescope.domain.entities.classification import MappingMethod
from cyclescope.domain.entities.data_source import DataSource
from cyclescope.domain.entities.industry import Industry
from cyclescope.domain.entities.industry_signal import (
    IndustrySignalType,
    IndustrySignalUnit,
)
from cyclescope.domain.entities.region import (
    Region,
    RegionRelationship,
    RegionRelationshipType,
    RegionType,
)
from cyclescope.domain.entities.sub_industry import SubIndustry
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.infrastructure.database.models.industry_signal import (
    IndustrySignalObservationModel,
)
from cyclescope.infrastructure.database.repositories.classification import (
    SQLAlchemyClassificationSchemeRepository,
    SQLAlchemyClassificationVersionRepository,
    SQLAlchemyIndustryClassificationMappingRepository,
)
from cyclescope.infrastructure.database.repositories.industry_signal import (
    SQLAlchemyIndustrySignalObservationRepository,
)
from cyclescope.infrastructure.database.repositories.master_data import (
    DataSourceSqlAlchemyRepository,
    IndustrySqlAlchemyRepository,
    SubIndustrySqlAlchemyRepository,
)
from cyclescope.infrastructure.database.repositories.region import (
    SQLAlchemyRegionRelationshipRepository,
    SQLAlchemyRegionRepository,
)
from cyclescope.infrastructure.database.session import create_database_engine


def test_versioned_mapping_resolution_and_signal_provenance(session: Session) -> None:
    schemes = SQLAlchemyClassificationSchemeRepository(session)
    versions = SQLAlchemyClassificationVersionRepository(session)
    mappings = SQLAlchemyIndustryClassificationMappingRepository(session)
    industries = IndustrySqlAlchemyRepository(session)
    sub_industries = SubIndustrySqlAlchemyRepository(session)
    sources = DataSourceSqlAlchemyRepository(session)
    signals = SQLAlchemyIndustrySignalObservationRepository(session)
    industry = industries.create(Industry(code="METALS", name="Metals"))
    sub_industry = sub_industries.create(
        SubIndustry(industry_id=industry.id or 0, code="STEEL", name="Steel")
    )
    source = sources.create(DataSource("SOURCE", "Source", "test"))

    scheme = (
        RegisterClassificationScheme(schemes)
        .execute(CreateClassificationSchemeRequest("TEST_CLASS", "Test", "Publisher"))
        .scheme
    )
    assert scheme is not None and scheme.id is not None
    version = (
        RegisterClassificationVersion(schemes, versions)
        .execute(
            CreateClassificationVersionRequest(
                scheme.id, "V1", date(2020, 1, 1), date(2025, 12, 31)
            )
        )
        .version
    )
    assert version is not None and version.id is not None
    mapping = (
        RegisterIndustryClassificationMapping(
            mappings, versions, industries, sub_industries
        )
        .execute(
            CreateIndustryClassificationMappingRequest(
                version.id,
                "EXT-01",
                "External Steel",
                industry.id or 0,
                date(2021, 1, 1),
                MappingMethod.MANUAL,
                internal_sub_industry_id=sub_industry.id,
                valid_to=date(2024, 12, 31),
                confidence=Decimal("0.95"),
            )
        )
        .mapping
    )
    assert mapping is not None and mapping.id is not None

    resolve = ResolveIndustryClassification(
        schemes, versions, mappings, industries, sub_industries
    )
    historical = resolve.execute(
        ResolveIndustryClassificationRequest(
            "TEST_CLASS", "V1", "EXT-01", date(2022, 6, 1)
        )
    )
    assert historical.mapping.id == mapping.id
    assert historical.industry.id == industry.id
    assert historical.sub_industry is not None
    assert historical.sub_industry.id == sub_industry.id
    with pytest.raises(DomainValidationError, match="No mapping"):
        resolve.execute(
            ResolveIndustryClassificationRequest(
                "TEST_CLASS", "V1", "EXT-01", date(2025, 1, 1)
            )
        )

    importer = ImportIndustrySignals(
        signals, industries, sub_industries, sources, mappings, versions
    )
    observation = IndustrySignalInput(
        industry_id=industry.id or 0,
        sub_industry_id=sub_industry.id,
        source_id=source.id or 0,
        signal_type=IndustrySignalType.INVENTORY,
        region_code="JP",
        observation_date=date(2022, 5, 31),
        period_start=None,
        period_end=None,
        value=Decimal("12"),
        unit_code=IndustrySignalUnit.TONNE,
        currency_code=None,
        publication_date=date(2022, 6, 1),
        publication_datetime=datetime(2022, 6, 1, tzinfo=UTC),
        available_at=datetime(2022, 6, 1, tzinfo=UTC),
        collected_at=datetime(2024, 1, 1, tzinfo=UTC),
        revision_number=1,
        classification_version_id=version.id,
        classification_mapping_id=mapping.id,
    )
    stored = importer.execute(
        ImportIndustrySignalsRequest((observation,))
    ).observations[0]
    assert stored.region_code == "JP"
    assert stored.classification_version_id == version.id
    assert stored.classification_mapping_id == mapping.id

    session.rollback()
    assert session.query(IndustrySignalObservationModel).count() == 0


def test_mapping_registration_rejects_overlapping_validity(session: Session) -> None:
    schemes = SQLAlchemyClassificationSchemeRepository(session)
    versions = SQLAlchemyClassificationVersionRepository(session)
    mappings = SQLAlchemyIndustryClassificationMappingRepository(session)
    industries = IndustrySqlAlchemyRepository(session)
    sub_industries = SubIndustrySqlAlchemyRepository(session)
    industry = industries.create(Industry(code="TECH", name="Technology"))
    scheme = (
        RegisterClassificationScheme(schemes)
        .execute(CreateClassificationSchemeRequest("TEST_MAP", "Test", "Publisher"))
        .scheme
    )
    assert scheme is not None and scheme.id is not None
    version = (
        RegisterClassificationVersion(schemes, versions)
        .execute(
            CreateClassificationVersionRequest(
                scheme.id, "V1", date(2020, 1, 1), date(2030, 12, 31)
            )
        )
        .version
    )
    assert version is not None and version.id is not None
    register = RegisterIndustryClassificationMapping(
        mappings, versions, industries, sub_industries
    )
    request = CreateIndustryClassificationMappingRequest(
        version.id,
        "CODE",
        "Code",
        industry.id or 0,
        date(2021, 1, 1),
        MappingMethod.EXACT,
        valid_to=date(2024, 12, 31),
    )
    register.execute(request)
    with pytest.raises(DomainValidationError, match="overlaps"):
        register.execute(
            CreateIndustryClassificationMappingRequest(
                version.id,
                "CODE",
                "Changed target",
                industry.id or 0,
                date(2022, 1, 1),
                MappingMethod.MANUAL,
                valid_to=date(2025, 12, 31),
            )
        )


def test_region_hierarchy_traversal_and_rollback(
    session: Session,
) -> None:
    regions = SQLAlchemyRegionRepository(session)
    relationships = SQLAlchemyRegionRelationshipRepository(session)
    register_region = RegisterRegion(regions)
    register_edge = RegisterRegionRelationship(regions, relationships)
    global_region = register_region.execute(
        CreateRegionRequest("GLOBAL", "Global", RegionType.GLOBAL)
    ).region
    asia = register_region.execute(
        CreateRegionRequest("ASIA", "Asia", RegionType.CONTINENT)
    ).region
    japan = register_region.execute(
        CreateRegionRequest("JP", "Japan", RegionType.COUNTRY)
    ).region
    assert global_region and asia and japan
    register_edge.execute(
        CreateRegionRelationshipRequest(global_region.id or 0, asia.id or 0)
    )
    register_edge.execute(CreateRegionRelationshipRequest(asia.id or 0, japan.id or 0))

    query = GetRegionAncestorPaths(regions, relationships)
    result = query.execute(GetRegionHierarchyRequest("JP"))
    assert [[item.region_code for item in path] for path in result.paths] == [
        ["GLOBAL", "ASIA"]
    ]
    descendant_result = GetRegionDescendants(regions, relationships).execute(
        GetRegionHierarchyRequest("GLOBAL")
    )
    assert {item.region_code for item in descendant_result.descendants} == {
        "ASIA",
        "JP",
    }
    session.rollback()
    assert regions.list() == []


def test_region_membership_is_distinct_from_geographic_containment(
    session: Session,
) -> None:
    regions = SQLAlchemyRegionRepository(session)
    relationships = SQLAlchemyRegionRelationshipRepository(session)
    add_region = RegisterRegion(regions)
    add_relationship = RegisterRegionRelationship(regions, relationships)

    global_region = add_region.execute(
        CreateRegionRequest("GLOBAL", "Global", RegionType.GLOBAL)
    ).region
    asia = add_region.execute(
        CreateRegionRequest("ASIA", "Asia", RegionType.CONTINENT)
    ).region
    japan = add_region.execute(
        CreateRegionRequest("JP", "Japan", RegionType.COUNTRY)
    ).region
    europe = add_region.execute(
        CreateRegionRequest("EUROPE", "Europe", RegionType.CONTINENT)
    ).region
    germany = add_region.execute(
        CreateRegionRequest("DE", "Germany", RegionType.COUNTRY)
    ).region
    france = add_region.execute(
        CreateRegionRequest("FR", "France", RegionType.COUNTRY)
    ).region
    eurozone = add_region.execute(
        CreateRegionRequest("EUROZONE", "Eurozone", RegionType.ECONOMIC_REGION)
    ).region
    market = add_region.execute(
        CreateRegionRequest("EU_MARKET", "EU Market", RegionType.MARKET_REGION)
    ).region
    assert all((global_region, asia, japan, europe, germany, france, eurozone, market))

    for parent, child in (
        (global_region, asia),
        (asia, japan),
        (global_region, europe),
        (europe, germany),
        (europe, france),
    ):
        add_relationship.execute(
            CreateRegionRelationshipRequest(parent.id or 0, child.id or 0)
        )
    for member in (germany, france):
        add_relationship.execute(
            CreateRegionRelationshipRequest(
                eurozone.id or 0,
                member.id or 0,
                RegionRelationshipType.MEMBER_OF,
            )
        )
    add_relationship.execute(
        CreateRegionRelationshipRequest(
            market.id or 0, germany.id or 0, RegionRelationshipType.MEMBER_OF
        )
    )

    japan_ancestors = GetRegionAncestorPaths(regions, relationships).execute(
        GetRegionHierarchyRequest("JP")
    )
    assert [[node.region_code for node in path] for path in japan_ancestors.paths] == [
        ["GLOBAL", "ASIA"]
    ]
    asia_descendants = GetRegionDescendants(regions, relationships).execute(
        GetRegionHierarchyRequest("ASIA")
    )
    assert [node.region_code for node in asia_descendants.descendants] == ["JP"]
    eurozone_members = GetRegionMembers(regions, relationships).execute(
        GetRegionHierarchyRequest("EUROZONE")
    )
    assert [node.region_code for node in eurozone_members.members] == ["DE", "FR"]
    germany_memberships = GetRegionMemberships(regions, relationships).execute(
        GetRegionHierarchyRequest("DE")
    )
    assert [node.region_code for node in germany_memberships.memberships] == [
        "EUROZONE",
        "EU_MARKET",
    ]

    with pytest.raises(DomainValidationError, match="already exists"):
        add_relationship.execute(
            CreateRegionRelationshipRequest(
                eurozone.id or 0,
                germany.id or 0,
                RegionRelationshipType.MEMBER_OF,
            )
        )


def test_region_relationship_validation_rejects_bad_types_and_containment_cycles(
    session: Session,
) -> None:
    regions = SQLAlchemyRegionRepository(session)
    relationships = SQLAlchemyRegionRelationshipRepository(session)
    add_region = RegisterRegion(regions)
    add_relationship = RegisterRegionRelationship(regions, relationships)
    world = add_region.execute(
        CreateRegionRequest("GLOBAL", "Global", RegionType.GLOBAL)
    ).region
    asia = add_region.execute(
        CreateRegionRequest("ASIA", "Asia", RegionType.CONTINENT)
    ).region
    japan = add_region.execute(
        CreateRegionRequest("JP", "Japan", RegionType.COUNTRY)
    ).region
    assert world and asia and japan
    add_relationship.execute(
        CreateRegionRelationshipRequest(world.id or 0, asia.id or 0)
    )
    add_relationship.execute(
        CreateRegionRelationshipRequest(asia.id or 0, japan.id or 0)
    )
    with pytest.raises(DomainValidationError, match="cannot contain cycles"):
        add_relationship.execute(
            CreateRegionRelationshipRequest(japan.id or 0, world.id or 0)
        )
    with pytest.raises(DomainValidationError, match="not allowed"):
        add_relationship.execute(
            CreateRegionRelationshipRequest(
                japan.id or 0, asia.id or 0, RegionRelationshipType.MEMBER_OF
            )
        )
    with pytest.raises(DomainValidationError, match="relationship_type"):
        RegionRelationship(1, 2, "UNKNOWN")  # type: ignore[arg-type]


def test_region_database_rejects_duplicate_codes_and_invalid_foreign_keys(
    session: Session,
) -> None:
    regions = SQLAlchemyRegionRepository(session)
    region = regions.create(Region("JP", "Japan", RegionType.COUNTRY, is_active=False))
    assert regions.get_by_id(region.id or 0) == region
    with pytest.raises(DomainValidationError, match="already exists"):
        regions.create(Region("JP", "Duplicate", RegionType.COUNTRY))
    with pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO region_relationships "
                "(parent_region_id, child_region_id, relationship_type, "
                "created_at, updated_at) "
                "VALUES (999, 998, 'CONTAINS', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )


def test_migration_preserves_existing_master_and_signal_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "classification_migration.db"
    config = Config(str(Path.cwd() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0020_industry_signal_observations")
    engine = create_database_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO industries (id, code, name, is_active, "
                "created_at, updated_at) "
                "VALUES (71, 'LEGACY', 'Legacy industry', 1, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO data_sources "
                "(id, code, name, provider_type, is_active, created_at, "
                "updated_at) "
                "VALUES (72, 'LEGACY_SOURCE', 'Legacy source', 'test', 1, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO industry_signal_observations "
                "(id, industry_id, source_id, signal_type, temporal_kind, region_code, "
                "observation_date, value, unit_code, publication_date, available_at, "
                "collected_at, revision_number, created_at, updated_at) "
                "VALUES (73, 71, 72, 'INVENTORY', 'POINT', 'legacy-region', "
                "'2024-01-31', 10, 'TONNE', '2024-02-01', '2024-02-01', "
                "'2024-02-03', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        signal = connection.execute(
            text(
                "SELECT id, industry_id, region_code, classification_version_id, "
                "classification_mapping_id FROM industry_signal_observations "
                "WHERE id=73"
            )
        ).one()
        assert tuple(signal) == (73, 71, "legacy-region", None, None)
        assert (
            connection.execute(
                text("SELECT id FROM industries WHERE id=71")
            ).scalar_one()
            == 71
        )
        table_names = set(inspect(connection).get_table_names())
        assert {
            "classification_schemes",
            "classification_versions",
            "industry_classification_mappings",
            "regions",
            "region_relationships",
        } <= table_names

    command.downgrade(config, "0020_industry_signal_observations")
    with engine.connect() as connection:
        signal = connection.execute(
            text(
                "SELECT id, industry_id, region_code FROM "
                "industry_signal_observations WHERE id=73"
            )
        ).one()
        assert tuple(signal) == (73, 71, "legacy-region")
        assert "regions" not in inspect(connection).get_table_names()
    engine.dispose()


def test_membership_migration_preserves_edge_ids_and_guards_downgrade(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "region_membership_migration.db"
    config = Config(str(Path.cwd() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0021_classification_and_region_masters")
    engine = create_database_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO regions (id, region_code, name, region_type, "
                "is_active, created_at, updated_at) "
                "VALUES (:id, :code, :name, :type, 1, CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP)"
            ),
            [
                {"id": 801, "code": "GLOBAL", "name": "Global", "type": "GLOBAL"},
                {"id": 802, "code": "ASIA", "name": "Asia", "type": "CONTINENT"},
                {"id": 803, "code": "JP", "name": "Japan", "type": "COUNTRY"},
                {
                    "id": 804,
                    "code": "ECON",
                    "name": "Economic region",
                    "type": "ECONOMIC_REGION",
                },
            ],
        )
        connection.execute(
            text(
                "INSERT INTO region_relationships (id, parent_region_id, "
                "child_region_id, relationship_type, created_at, updated_at) "
                "VALUES (805, 801, 802, 'CONTAINS', CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(config, "head")
    with engine.begin() as connection:
        old_edge = connection.execute(
            text(
                "SELECT id, parent_region_id, child_region_id, relationship_type "
                "FROM region_relationships WHERE id=805"
            )
        ).one()
        assert tuple(old_edge) == (805, 801, 802, "CONTAINS")
        connection.execute(
            text(
                "INSERT INTO region_relationships (id, parent_region_id, "
                "child_region_id, relationship_type, created_at, updated_at) "
                "VALUES (806, 804, 803, 'MEMBER_OF', CURRENT_TIMESTAMP, "
                "CURRENT_TIMESTAMP)"
            )
        )
    with pytest.raises(RuntimeError, match="Cannot downgrade"):
        command.downgrade(config, "0021_classification_and_region_masters")
    with engine.begin() as connection:
        assert (
            connection.execute(
                text("SELECT id FROM region_relationships WHERE id=805")
            ).scalar_one()
            == 805
        )
        connection.execute(text("DELETE FROM region_relationships WHERE id=806"))
    command.downgrade(config, "0021_classification_and_region_masters")
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT id, relationship_type FROM region_relationships WHERE id=805")
        ).one() == (805, "CONTAINS")
    engine.dispose()
