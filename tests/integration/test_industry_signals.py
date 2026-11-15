"""SQLite integration tests for industry signal PIT storage and retrieval."""

from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from cyclescope.application.dto.industry_signal import (
    GetIndustrySignalsRequest,
    ImportIndustrySignalsRequest,
    IndustrySignalInput,
)
from cyclescope.application.use_cases.industry_signals import (
    GetIndustrySignals,
    ImportIndustrySignals,
)
from cyclescope.domain.entities.data_source import DataSource
from cyclescope.domain.entities.industry import Industry
from cyclescope.domain.entities.industry_signal import (
    IndustrySignalObservation,
    IndustrySignalType,
    IndustrySignalUnit,
)
from cyclescope.domain.entities.sub_industry import SubIndustry
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.infrastructure.database.models import IndustrySignalObservationModel
from cyclescope.infrastructure.database.repositories.industry_signal import (
    SQLAlchemyIndustrySignalObservationRepository,
)
from cyclescope.infrastructure.database.repositories.master_data import (
    DataSourceSqlAlchemyRepository,
    IndustrySqlAlchemyRepository,
    SubIndustrySqlAlchemyRepository,
)
from cyclescope.infrastructure.database.session import create_database_engine

AS_OF = datetime(2025, 3, 15, 12, tzinfo=UTC)


def _harness(session: Session):
    industries = IndustrySqlAlchemyRepository(session)
    sub_industries = SubIndustrySqlAlchemyRepository(session)
    sources = DataSourceSqlAlchemyRepository(session)
    observations = SQLAlchemyIndustrySignalObservationRepository(session)
    industry = industries.create(Industry(code="MATERIALS", name="Materials"))
    other_industry = industries.create(Industry(code="CHEMICALS", name="Chemicals"))
    sub_industry = sub_industries.create(
        SubIndustry(industry_id=industry.id or 0, code="STEEL", name="Steel")
    )
    other_sub_industry = sub_industries.create(
        SubIndustry(industry_id=other_industry.id or 0, code="RESIN", name="Resin")
    )
    source1 = sources.create(DataSource("SOURCE_1", "Source 1", "test"))
    source2 = sources.create(DataSource("SOURCE_2", "Source 2", "test"))
    importer = ImportIndustrySignals(observations, industries, sub_industries, sources)
    query = GetIndustrySignals(observations, industries, sub_industries)
    return (
        observations,
        importer,
        query,
        industry,
        other_industry,
        sub_industry,
        other_sub_industry,
        source1,
        source2,
    )


def _input(
    source_id: int,
    *,
    value: Decimal | None = Decimal("10.5"),
    revision: int = 1,
    available_at: datetime = datetime(2025, 3, 1, tzinfo=UTC),
    publication_datetime: datetime | None = datetime(2025, 3, 1, tzinfo=UTC),
    observed_on: date | None = date(2025, 2, 28),
    signal_type: IndustrySignalType = IndustrySignalType.INVENTORY,
    unit_code: IndustrySignalUnit = IndustrySignalUnit.TONNE,
    currency_code: str | None = None,
    industry_id: int = 1,
    sub_industry_id: int | None = None,
    region_code: str = "JP",
    collected_at: datetime = datetime(2025, 3, 30, tzinfo=UTC),
    missing_reason: str | None = None,
    period_start: date | None = None,
    period_end: date | None = None,
) -> IndustrySignalInput:
    return IndustrySignalInput(
        industry_id=industry_id,
        sub_industry_id=sub_industry_id,
        source_id=source_id,
        signal_type=signal_type,
        region_code=region_code,
        observation_date=observed_on,
        period_start=period_start,
        period_end=period_end,
        value=value,
        unit_code=unit_code,
        currency_code=currency_code,
        publication_date=publication_datetime.date()
        if publication_datetime
        else available_at.date(),
        publication_datetime=publication_datetime,
        available_at=available_at,
        collected_at=collected_at,
        revision_number=revision,
        source_reference=f"source-row-{revision}",
        missing_reason=missing_reason,
    )


def test_import_and_round_trip_preserve_all_provenance(session: Session) -> None:
    (
        _,
        importer,
        query,
        industry,
        _,
        sub_industry,
        _,
        source,
        _,
    ) = _harness(session)
    item = _input(
        source.id or 0,
        industry_id=industry.id or 0,
        sub_industry_id=sub_industry.id,
    )

    stored = importer.execute(ImportIndustrySignalsRequest((item,))).observations[0]
    fetched = query.execute(
        GetIndustrySignalsRequest(
            industry.id or 0,
            AS_OF,
            sub_industry_id=sub_industry.id,
            region_code="JP",
            source_id=source.id,
        )
    ).observations[0]

    assert fetched.id == stored.id
    assert fetched.value == Decimal("10.5")
    assert fetched.sub_industry_id == sub_industry.id
    assert fetched.available_at == datetime(2025, 3, 1, tzinfo=UTC)
    assert fetched.collected_at == datetime(2025, 3, 30, tzinfo=UTC)
    assert fetched.source_reference == "source-row-1"


def test_import_rejects_unknown_and_mismatched_industry_references(
    session: Session,
) -> None:
    (
        _,
        importer,
        _,
        industry,
        _,
        _,
        other_sub_industry,
        source,
        _,
    ) = _harness(session)
    with pytest.raises(DomainValidationError, match="Unknown industry"):
        importer.execute(
            ImportIndustrySignalsRequest((_input(source.id or 0, industry_id=999),))
        )
    with pytest.raises(DomainValidationError, match="does not belong"):
        importer.execute(
            ImportIndustrySignalsRequest(
                (
                    _input(
                        source.id or 0,
                        industry_id=industry.id or 0,
                        sub_industry_id=other_sub_industry.id,
                    ),
                )
            )
        )
    with pytest.raises(DomainValidationError, match="Unknown data source"):
        importer.execute(
            ImportIndustrySignalsRequest((_input(999, industry_id=industry.id or 0),))
        )


def test_pit_revision_selection_ignores_later_revision_and_collection_time(
    session: Session,
) -> None:
    observations, importer, query, industry, _, _, _, source, _ = _harness(session)
    first = _input(source.id or 0, industry_id=industry.id or 0, revision=1)
    later = _input(
        source.id or 0,
        industry_id=industry.id or 0,
        value=Decimal("12"),
        revision=2,
        available_at=datetime(2025, 3, 20, tzinfo=UTC),
        publication_datetime=datetime(2025, 3, 20, tzinfo=UTC),
    )
    importer.execute(ImportIndustrySignalsRequest((first, later)))

    historical = query.execute(
        GetIndustrySignalsRequest(industry.id or 0, AS_OF, source_id=source.id)
    ).observations
    assert len(historical) == 1
    assert historical[0].revision_number == 1
    assert historical[0].collected_at > AS_OF
    assert (
        observations.list_available_as_of(
            industry.id or 0,
            AS_OF,
            source_id=source.id,
        )[0].revision_number
        == 1
    )

    current = query.execute(
        GetIndustrySignalsRequest(
            industry.id or 0,
            datetime(2025, 3, 25, tzinfo=UTC),
            source_id=source.id,
        )
    ).observations
    assert current[0].revision_number == 2


def test_future_observation_period_is_hidden_until_period_end(session: Session) -> None:
    _, importer, query, industry, _, _, _, source, _ = _harness(session)
    future_period = _input(
        source.id or 0,
        industry_id=industry.id or 0,
        signal_type=IndustrySignalType.PRODUCTION,
        observed_on=None,
        period_start=date(2025, 3, 1),
        period_end=date(2025, 3, 31),
    )
    importer.execute(ImportIndustrySignalsRequest((future_period,)))

    result = query.execute(
        GetIndustrySignalsRequest(industry.id or 0, AS_OF, source_id=source.id)
    )
    assert result.observations == ()
    result = query.execute(
        GetIndustrySignalsRequest(
            industry.id or 0,
            datetime(2025, 4, 1, tzinfo=UTC),
            source_id=source.id,
        )
    )
    assert result.observations[0].period_end == date(2025, 3, 31)


def test_source_ambiguity_requires_explicit_source_and_never_merges(
    session: Session,
) -> None:
    _, importer, query, industry, _, _, _, source1, source2 = _harness(session)
    importer.execute(
        ImportIndustrySignalsRequest(
            (
                _input(source1.id or 0, industry_id=industry.id or 0),
                _input(source2.id or 0, industry_id=industry.id or 0),
            )
        )
    )

    with pytest.raises(DomainValidationError, match="source_id is required"):
        query.execute(GetIndustrySignalsRequest(industry.id or 0, AS_OF))
    result = query.execute(
        GetIndustrySignalsRequest(industry.id or 0, AS_OF, source_id=source1.id)
    )
    assert len(result.observations) == 1
    assert result.observations[0].source_id == source1.id


def test_missing_values_remain_null_and_duplicate_revision_is_rejected(
    session: Session,
) -> None:
    observations, importer, query, industry, _, _, _, source, _ = _harness(session)
    missing = _input(
        source.id or 0,
        industry_id=industry.id or 0,
        value=None,
        missing_reason="Provider did not report the value.",
    )
    stored = importer.execute(ImportIndustrySignalsRequest((missing,))).observations[0]
    assert stored.value is None
    assert stored.missing_reason == "Provider did not report the value."
    assert (
        query.execute(
            GetIndustrySignalsRequest(industry.id or 0, AS_OF, source_id=source.id)
        )
        .observations[0]
        .value
        is None
    )
    with pytest.raises(DomainValidationError, match="already exists"):
        importer.execute(ImportIndustrySignalsRequest((missing,)))
    assert session.query(IndustrySignalObservationModel).count() == 1
    assert not hasattr(observations, "update")
    assert not hasattr(observations, "delete")


def test_announced_and_completed_closures_persist_separately(session: Session) -> None:
    _, importer, query, industry, _, _, _, source, _ = _harness(session)
    announced = _input(
        source.id or 0,
        industry_id=industry.id or 0,
        signal_type=IndustrySignalType.CAPACITY_CLOSURE_ANNOUNCED,
    )
    completed = _input(
        source.id or 0,
        industry_id=industry.id or 0,
        signal_type=IndustrySignalType.CAPACITY_CLOSURE_COMPLETED,
    )
    importer.execute(ImportIndustrySignalsRequest((announced, completed)))

    result = query.execute(
        GetIndustrySignalsRequest(industry.id or 0, AS_OF, source_id=source.id)
    )
    assert {row.signal_type for row in result.observations} == {
        IndustrySignalType.CAPACITY_CLOSURE_ANNOUNCED,
        IndustrySignalType.CAPACITY_CLOSURE_COMPLETED,
    }


def test_repository_does_not_commit_and_caller_rollback_removes_insert(
    session: Session,
) -> None:
    observations, _, _, industry, _, _, _, source, _ = _harness(session)
    item = _input(source.id or 0, industry_id=industry.id or 0)
    record = IndustrySignalObservation(**asdict(item))
    observations.create(record)
    session.rollback()
    assert session.query(IndustrySignalObservationModel).count() == 0


def test_industry_signal_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    database_path = tmp_path / "industry_signal_migration.db"
    config = Config(str(Path.cwd() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0019_optional_pl_period_start")
    command.upgrade(config, "head")
    engine = create_database_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        assert "industry_signal_observations" in inspect(connection).get_table_names()
        index_names = {
            index["name"]
            for index in inspect(connection).get_indexes("industry_signal_observations")
        }
        assert "uq_industry_signal_period_revision_subindustry" in index_names
    command.downgrade(config, "0019_optional_pl_period_start")
    with engine.connect() as connection:
        assert (
            "industry_signal_observations" not in inspect(connection).get_table_names()
        )
    engine.dispose()
