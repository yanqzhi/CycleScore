"""Real SQLite tests for aggregation orchestration and immutable persistence."""

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from cyclescope.application.dto.industry_signal import (
    ImportIndustrySignalsRequest,
    IndustrySignalInput,
)
from cyclescope.application.dto.industry_signal_aggregation import (
    AggregateIndustrySignalsRequest,
    GetIndustrySignalAggregateRequest,
)
from cyclescope.application.use_cases.industry_signal_aggregation import (
    AggregateIndustrySignals,
    GetIndustrySignalAggregate,
)
from cyclescope.application.use_cases.industry_signals import (
    GetIndustrySignals,
    ImportIndustrySignals,
)
from cyclescope.domain.entities.data_source import DataSource
from cyclescope.domain.entities.industry import Industry
from cyclescope.domain.entities.industry_signal import (
    IndustrySignalType,
    IndustrySignalUnit,
)
from cyclescope.domain.entities.region import (
    Region,
    RegionRelationship,
    RegionType,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.infrastructure.database.models.industry_signal_aggregate import (
    IndustrySignalAggregateModel,
)
from cyclescope.infrastructure.database.repositories.industry_signal import (
    SQLAlchemyIndustrySignalObservationRepository,
)
from cyclescope.infrastructure.database.repositories.industry_signal_aggregate import (
    SQLAlchemyIndustrySignalAggregateRepository,
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

AS_OF = datetime(2025, 4, 15, 12, tzinfo=UTC)
PERIOD_START = date(2025, 3, 1)
PERIOD_END = date(2025, 3, 31)


def _setup(session: Session):
    industries = IndustrySqlAlchemyRepository(session)
    sub_industries = SubIndustrySqlAlchemyRepository(session)
    sources = DataSourceSqlAlchemyRepository(session)
    observations = SQLAlchemyIndustrySignalObservationRepository(session)
    regions = SQLAlchemyRegionRepository(session)
    relationships = SQLAlchemyRegionRelationshipRepository(session)
    industry = industries.create(Industry(code="MATERIALS", name="Materials"))
    source = sources.create(DataSource("SOURCE_1", "Source 1", "test"))
    world = regions.create(Region("WORLD", "World", RegionType.GLOBAL))
    jp = regions.create(Region("JP", "Japan", RegionType.COUNTRY))
    us = regions.create(Region("US", "United States", RegionType.COUNTRY))
    relationships.create(RegionRelationship(world.id or 0, jp.id or 0))
    relationships.create(RegionRelationship(world.id or 0, us.id or 0))
    importer = ImportIndustrySignals(
        observations,
        industries,
        sub_industries,
        sources,
    )
    query = GetIndustrySignals(observations, industries, sub_industries)
    aggregate_repo = SQLAlchemyIndustrySignalAggregateRepository(session)
    aggregate = AggregateIndustrySignals(query, aggregate_repo, regions, relationships)
    return aggregate, importer, aggregate_repo, industry, source


def _input(
    industry_id: int,
    source_id: int,
    region: str,
    value: str,
    *,
    signal: IndustrySignalType = IndustrySignalType.PRODUCTION,
    available: datetime = datetime(2025, 4, 1, tzinfo=UTC),
    revision: int = 1,
    unit: IndustrySignalUnit = IndustrySignalUnit.TONNE,
    start: date | None = PERIOD_START,
    end: date | None = PERIOD_END,
    observed: date | None = None,
) -> IndustrySignalInput:
    return IndustrySignalInput(
        industry_id=industry_id,
        source_id=source_id,
        signal_type=signal,
        region_code=region,
        observation_date=observed,
        period_start=start,
        period_end=end,
        value=Decimal(value),
        unit_code=unit,
        currency_code=None,
        publication_date=available.date(),
        publication_datetime=available,
        available_at=available,
        collected_at=datetime(2025, 5, 1, tzinfo=UTC),
        revision_number=revision,
        source_reference=f"{region}-{revision}",
    )


def _request(industry_id: int, source_id: int) -> AggregateIndustrySignalsRequest:
    return AggregateIndustrySignalsRequest(
        industry_id=industry_id,
        signal_type=IndustrySignalType.PRODUCTION,
        aggregate_region_code="WORLD",
        constituent_region_codes=("JP", "US"),
        policy_code="FLOW_SUM",
        policy_version=1,
        unit_code=IndustrySignalUnit.TONNE,
        as_of=AS_OF,
        source_id=source_id,
        period_start=PERIOD_START,
        period_end=PERIOD_END,
        expected_contributor_count=2,
    )


def test_sqlite_aggregate_uses_pit_revisions_and_roundtrips_provenance(
    session: Session,
) -> None:
    aggregate, importer, repo, industry, source = _setup(session)
    importer.execute(
        ImportIndustrySignalsRequest(
            (
                _input(industry.id or 0, source.id or 0, "JP", "10"),
                _input(industry.id or 0, source.id or 0, "US", "20"),
                _input(
                    industry.id or 0,
                    source.id or 0,
                    "JP",
                    "999",
                    available=datetime(2025, 4, 20, tzinfo=UTC),
                    revision=2,
                ),
            )
        )
    )
    snapshot = aggregate.execute(_request(industry.id or 0, source.id or 0)).snapshot
    fetched = (
        GetIndustrySignalAggregate(repo)
        .execute(GetIndustrySignalAggregateRequest(snapshot.id or 0))
        .snapshot
    )
    assert fetched.value == Decimal("30.000000000000")
    assert [c.region_code for c in fetched.contributors] == ["JP", "US"]
    assert [c.revision_number for c in fetched.contributors] == [1, 1]
    assert all(c.available_at <= AS_OF for c in fetched.contributors)
    assert all(c.collected_at > AS_OF for c in fetched.contributors)
    assert len(repo.list_by_industry(industry.id or 0)) == 1


def test_snapshot_and_contributors_follow_caller_rollback(session: Session) -> None:
    aggregate, importer, _, industry, source = _setup(session)
    importer.execute(
        ImportIndustrySignalsRequest(
            (
                _input(industry.id or 0, source.id or 0, "JP", "10"),
                _input(industry.id or 0, source.id or 0, "US", "20"),
            )
        )
    )
    with pytest.raises(RuntimeError, match="rollback"):
        with session.begin_nested():
            aggregate.execute(_request(industry.id or 0, source.id or 0))
            raise RuntimeError("rollback")
    assert session.query(IndustrySignalAggregateModel).count() == 0


def test_recalculation_is_append_only_and_source_ambiguity_is_not_mixed(
    session: Session,
) -> None:
    aggregate, importer, repo, industry, source = _setup(session)
    importer.execute(
        ImportIndustrySignalsRequest(
            (
                _input(industry.id or 0, source.id or 0, "JP", "10"),
                _input(industry.id or 0, source.id or 0, "US", "20"),
            )
        )
    )
    first = aggregate.execute(_request(industry.id or 0, source.id or 0)).snapshot
    second = aggregate.execute(_request(industry.id or 0, source.id or 0)).snapshot
    assert first.id != second.id
    assert len(repo.list_by_industry(industry.id or 0)) == 2
    assert repo.get_by_id(first.id or 0) == first

    other = DataSourceSqlAlchemyRepository(session).create(
        DataSource("SOURCE_2", "Source 2", "test")
    )
    importer.execute(
        ImportIndustrySignalsRequest(
            (_input(industry.id or 0, other.id or 0, "JP", "50"),)
        )
    )
    with pytest.raises(DomainValidationError, match="source_id is required"):
        aggregate.execute(
            AggregateIndustrySignalsRequest(
                industry_id=industry.id or 0,
                signal_type=IndustrySignalType.PRODUCTION,
                aggregate_region_code="WORLD",
                constituent_region_codes=("JP",),
                policy_code="FLOW_SUM",
                policy_version=1,
                unit_code=IndustrySignalUnit.TONNE,
                as_of=AS_OF,
                period_start=PERIOD_START,
                period_end=PERIOD_END,
            )
        )


def test_overlap_is_rejected_before_aggregate_creation(session: Session) -> None:
    aggregate, _, _, industry, _ = _setup(session)
    with pytest.raises(DomainValidationError, match="Non-overlap"):
        aggregate.execute(
            AggregateIndustrySignalsRequest(
                industry_id=industry.id or 0,
                signal_type=IndustrySignalType.INVENTORY,
                aggregate_region_code="WORLD",
                constituent_region_codes=("WORLD", "JP"),
                policy_code="INVENTORY_SUM",
                policy_version=1,
                unit_code=IndustrySignalUnit.TONNE,
                as_of=AS_OF,
                observation_date=PERIOD_END,
                expected_contributor_count=2,
            )
        )


def test_aggregate_migration_upgrade_and_downgrade_is_additive(tmp_path: Path) -> None:
    path = tmp_path / "aggregate_migration.db"
    config = Config(str(Path.cwd() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "0022_region_membership_relationships")
    engine = create_database_engine(f"sqlite:///{path}")
    before = set(inspect(engine).get_table_names())
    command.upgrade(config, "head")
    after = set(inspect(engine).get_table_names())
    assert "industry_signal_aggregates" in after
    assert "industry_signal_aggregate_contributors" in after
    assert before < after
    command.downgrade(config, "0022_region_membership_relationships")
    downgraded = set(inspect(engine).get_table_names())
    assert "industry_signal_aggregates" not in downgraded
    assert "industry_signal_aggregate_contributors" not in downgraded
    assert before <= downgraded
    engine.dispose()
