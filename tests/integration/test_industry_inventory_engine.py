"""SQLite integration coverage for industry inventory analysis and persistence."""

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cyclescope.application.dto.industry_inventory import (
    AnalyzeIndustryInventoryRequest,
)
from cyclescope.application.dto.industry_signal import (
    ImportIndustrySignalsRequest,
    IndustrySignalInput,
)
from cyclescope.application.dto.industry_signal_aggregation import (
    AggregateIndustrySignalsRequest,
)
from cyclescope.application.use_cases.industry_inventory import AnalyzeIndustryInventory
from cyclescope.application.use_cases.industry_signal_aggregation import (
    AggregateIndustrySignals,
)
from cyclescope.application.use_cases.industry_signals import (
    GetIndustrySignals,
    ImportIndustrySignals,
)
from cyclescope.domain.entities.data_source import DataSource
from cyclescope.domain.entities.industry import Industry
from cyclescope.domain.entities.industry_inventory import (
    IndustryInventoryClassification,
    IndustryInventoryConfig,
    IndustryInventoryStatus,
    IndustryInventoryTrend,
)
from cyclescope.domain.entities.industry_signal import (
    IndustrySignalType,
    IndustrySignalUnit,
)
from cyclescope.domain.entities.region import Region, RegionRelationship, RegionType
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.services.industry_inventory import calculate_industry_inventory
from cyclescope.infrastructure.database.models.industry_inventory import (
    IndustryInventoryInputModel,
    IndustryInventoryScopeModel,
    IndustryInventorySnapshotModel,
)
from cyclescope.infrastructure.database.repositories.industry_inventory import (
    SQLAlchemyIndustryInventoryRepository,
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
    importer = ImportIndustrySignals(observations, industries, sub_industries, sources)
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
    signal: IndustrySignalType,
    available: datetime,
    start: date | None,
    end: date | None,
    observed: date | None = None,
    revision: int = 1,
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
        unit_code=IndustrySignalUnit.TONNE,
        publication_date=available.date(),
        publication_datetime=available,
        available_at=available,
        collected_at=datetime(2026, 2, 2, tzinfo=UTC),
        revision_number=revision,
        source_reference=f"{region}-{signal.value}-{observed or end}-{revision}",
    )


CUTOFF = datetime(2026, 2, 1, tzinfo=UTC)


def _config(minimum_coverage: Decimal = Decimal("0.80")) -> IndustryInventoryConfig:
    """Explicit test policy; production thresholds require calibration."""
    return IndustryInventoryConfig(
        version=1,
        accumulation_yoy=Decimal("0.05"),
        rapid_accumulation_yoy=Decimal("0.20"),
        normalization_prior_yoy=Decimal("-0.10"),
        normalization_growth_ceiling=Decimal("0.05"),
        stable_growth_tolerance=Decimal("0.02"),
        gap_ratio_tolerance=Decimal("0.02"),
        minimum_coverage=minimum_coverage,
        expected_observation_interval_months=12,
    )


def _aggregate_series(
    session: Session,
    *,
    missing_current_region: str | None = None,
    omitted_inventory_date: date | None = None,
    mismatched_flow_start: bool = False,
    inventory_region_overrides: dict[date, tuple[str, ...]] | None = None,
    flow_region_overrides: dict[IndustrySignalType, tuple[str, ...]] | None = None,
):
    aggregate, importer, aggregate_repo, industry, source = _setup(session)
    signals = []
    values = (
        (date(2023, 12, 31), "80"),
        (date(2024, 12, 31), "90"),
        (date(2025, 12, 31), "110"),
    )
    for observed, total in values:
        available = datetime.combine(observed, datetime.min.time(), tzinfo=UTC)
        selected_regions = (inventory_region_overrides or {}).get(
            observed, ("JP", "US")
        )
        for region, value in (
            ("JP", str(Decimal(total) / 2)),
            ("US", str(Decimal(total) / 2)),
        ):
            if observed == omitted_inventory_date:
                continue
            if observed == date(2025, 12, 31) and region == missing_current_region:
                continue
            if region not in selected_regions:
                continue
            signals.append(
                _input(
                    industry.id or 0,
                    source.id or 0,
                    region,
                    value,
                    signal=IndustrySignalType.INVENTORY,
                    available=available,
                    start=None,
                    end=None,
                    observed=observed,
                )
            )
    signals.append(
        _input(
            industry.id or 0,
            source.id or 0,
            "JP",
            "900",
            signal=IndustrySignalType.INVENTORY,
            available=datetime(2026, 3, 1, tzinfo=UTC),
            start=None,
            end=None,
            observed=date(2025, 12, 31),
            revision=2,
        )
    )
    for signal, total in (
        (IndustrySignalType.PRODUCTION, "50"),
        (IndustrySignalType.SHIPMENTS, "40"),
    ):
        selected_regions = (flow_region_overrides or {}).get(signal, ("JP", "US"))
        for region in selected_regions:
            signals.append(
                _input(
                    industry.id or 0,
                    source.id or 0,
                    region,
                    str(Decimal(total) / 2),
                    signal=signal,
                    available=datetime(2026, 1, 15, tzinfo=UTC),
                    start=(
                        date(2025, 11, 1)
                        if mismatched_flow_start
                        and signal is IndustrySignalType.SHIPMENTS
                        else date(2025, 12, 1)
                    ),
                    end=date(2025, 12, 31),
                )
            )
    importer.execute(ImportIndustrySignalsRequest(tuple(signals)))
    region_rows = {row.region_code: row for row in aggregate.regions.list()}
    constituent_codes = ("JP", "US")
    scope = tuple(
        sorted((region_rows[code].id or 0, code) for code in constituent_codes)
    )
    for observed, _total in values:
        aggregate.execute(
            AggregateIndustrySignalsRequest(
                industry_id=industry.id or 0,
                signal_type=IndustrySignalType.INVENTORY,
                aggregate_region_code="WORLD",
                constituent_region_codes=constituent_codes,
                policy_code="INVENTORY_SUM",
                policy_version=1,
                unit_code=IndustrySignalUnit.TONNE,
                as_of=CUTOFF,
                source_id=source.id,
                observation_date=observed,
                expected_contributor_count=2,
                minimum_coverage=Decimal("0.40"),
            )
        )
    for signal in (IndustrySignalType.PRODUCTION, IndustrySignalType.SHIPMENTS):
        aggregate.execute(
            AggregateIndustrySignalsRequest(
                industry_id=industry.id or 0,
                signal_type=signal,
                aggregate_region_code="WORLD",
                constituent_region_codes=constituent_codes,
                policy_code="FLOW_SUM",
                policy_version=1,
                unit_code=IndustrySignalUnit.TONNE,
                as_of=CUTOFF,
                source_id=source.id,
                period_start=date(2025, 12, 1),
                period_end=date(2025, 12, 31),
                expected_contributor_count=2,
                minimum_coverage=Decimal("0.40"),
            )
        )
    return aggregate_repo, industry, source, scope


def test_analysis_persists_pit_metrics_scope_and_source_provenance(
    session: Session,
) -> None:
    aggregate_repo, industry, source, scope = _aggregate_series(session)
    repo = SQLAlchemyIndustryInventoryRepository(session)
    use_case = AnalyzeIndustryInventory(aggregate_repo, repo)
    result = use_case.execute(
        AnalyzeIndustryInventoryRequest(
            industry_id=industry.id or 0,
            aggregate_region_code="WORLD",
            requested_scope=scope,
            source_id=source.id,
            as_of=CUTOFF,
            config=_config(),
        )
    ).snapshot

    assert result.observation_date == date(2025, 12, 31)
    assert result.inventory_value == Decimal("110.000000000000")
    assert result.prior_inventory_value == Decimal("90.000000000000")
    assert result.yoy_growth == Decimal("0.222222222222")
    assert result.prior_yoy_growth == Decimal("0.125000000000")
    assert result.production_shipment_gap == Decimal("10.000000000000")
    assert result.classification is IndustryInventoryClassification.RAPID_ACCUMULATION
    assert result.trend is IndustryInventoryTrend.INCREASING
    assert result.status is IndustryInventoryStatus.AVAILABLE
    assert result.coverage == Decimal("1.0000000")
    assert len(result.input_references) == 6
    current_input = next(
        ref for ref in result.input_references if ref.role == "CURRENT_INVENTORY"
    )
    assert [revision[2] for revision in current_input.contributor_revisions] == [1, 1]

    fetched = repo.get_by_id(result.id or 0)
    assert fetched == result
    assert fetched is not None and fetched.requested_scope == scope
    assert fetched is not None and fetched.contributing_regions == scope
    assert all(ref.available_at <= CUTOFF for ref in fetched.input_references)
    assert all(
        revision[1] == (source.id or 0) and revision[2] == 1
        for ref in fetched.input_references
        for revision in ref.contributor_revisions
    )
    assert len(repo.list_by_industry(industry.id or 0, as_of=CUTOFF)) == 1


def test_analysis_write_obeys_caller_rollback(session: Session) -> None:
    aggregate_repo, industry, source, scope = _aggregate_series(session)
    repo = SQLAlchemyIndustryInventoryRepository(session)
    use_case = AnalyzeIndustryInventory(aggregate_repo, repo)
    with pytest.raises(RuntimeError, match="rollback"):
        with session.begin_nested():
            use_case.execute(
                AnalyzeIndustryInventoryRequest(
                    industry_id=industry.id or 0,
                    aggregate_region_code="WORLD",
                    requested_scope=scope,
                    source_id=source.id,
                    as_of=CUTOFF,
                    config=_config(),
                )
            )
            raise RuntimeError("rollback")
    assert session.query(IndustryInventorySnapshotModel).count() == 0
    assert session.query(IndustryInventoryInputModel).count() == 0
    assert session.query(IndustryInventoryScopeModel).count() == 0


def test_scope_rows_keep_sqlite_foreign_key_enforcement(session: Session) -> None:
    aggregate_repo, industry, source, scope = _aggregate_series(session)
    snapshot = (
        AnalyzeIndustryInventory(
            aggregate_repo, SQLAlchemyIndustryInventoryRepository(session)
        )
        .execute(
            AnalyzeIndustryInventoryRequest(
                industry_id=industry.id or 0,
                aggregate_region_code="WORLD",
                requested_scope=scope,
                source_id=source.id,
                as_of=CUTOFF,
                config=_config(),
            )
        )
        .snapshot
    )
    assert session.scalar(text("PRAGMA foreign_keys")) == 1
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.add(
                IndustryInventoryScopeModel(
                    snapshot_id=snapshot.id or 0,
                    region_id=999_999,
                    region_code="MISSING",
                    scope_role="CONTRIBUTING",
                )
            )
            session.flush()


def test_future_available_inventory_revision_is_excluded_from_historical_cutoff(
    session: Session,
) -> None:
    aggregate_repo, industry, source, scope = _aggregate_series(session)
    rows = aggregate_repo.list_by_industry(industry.id or 0, as_of=CUTOFF)
    future_rows = tuple(
        replace(
            row,
            contributors=tuple(
                replace(
                    item,
                    available_at=datetime(2026, 3, 1, tzinfo=UTC),
                )
                if row.signal_type is IndustrySignalType.INVENTORY
                and row.observation_date == date(2025, 12, 31)
                else item
                for item in row.contributors
            ),
        )
        for row in rows
    )
    result = calculate_industry_inventory(
        aggregates=future_rows,
        industry_id=industry.id or 0,
        aggregate_region_code="WORLD",
        requested_scope=scope,
        source_id=source.id,
        as_of=CUTOFF,
        calculated_at=CUTOFF,
        config=_config(),
    )
    assert result.observation_date == date(2024, 12, 31)
    assert all(
        ref.observation_date != date(2025, 12, 31) for ref in result.input_references
    )


def test_missing_region_is_retained_as_requested_but_not_actual_scope(
    session: Session,
) -> None:
    aggregate_repo, industry, source, scope = _aggregate_series(
        session, missing_current_region="US"
    )
    result = (
        AnalyzeIndustryInventory(
            aggregate_repo, SQLAlchemyIndustryInventoryRepository(session)
        )
        .execute(
            AnalyzeIndustryInventoryRequest(
                industry_id=industry.id or 0,
                aggregate_region_code="WORLD",
                requested_scope=scope,
                source_id=source.id,
                as_of=CUTOFF,
                config=_config(Decimal("0.40")),
            )
        )
        .snapshot
    )
    assert result.requested_scope == scope
    assert result.contributing_regions == (scope[0],)
    assert result.coverage == Decimal("0.5000000")
    assert result.status is IndustryInventoryStatus.INSUFFICIENT_DATA
    assert result.yoy_growth is None
    assert any("US" in reason for reason in result.unavailable_reasons)


def test_missing_calendar_anniversary_is_insufficient_not_zero(
    session: Session,
) -> None:
    aggregate_repo, industry, source, scope = _aggregate_series(
        session, omitted_inventory_date=date(2024, 12, 31)
    )
    result = (
        AnalyzeIndustryInventory(
            aggregate_repo, SQLAlchemyIndustryInventoryRepository(session)
        )
        .execute(
            AnalyzeIndustryInventoryRequest(
                industry_id=industry.id or 0,
                aggregate_region_code="WORLD",
                requested_scope=scope,
                source_id=source.id,
                as_of=CUTOFF,
                config=_config(),
            )
        )
        .snapshot
    )
    assert result.yoy_growth is None
    assert result.status is IndustryInventoryStatus.INSUFFICIENT_DATA
    assert any("anniversary" in reason for reason in result.unavailable_reasons)


def test_mismatched_flow_periods_are_not_compared(session: Session) -> None:
    aggregate_repo, industry, source, scope = _aggregate_series(
        session, mismatched_flow_start=True
    )
    result = (
        AnalyzeIndustryInventory(
            aggregate_repo, SQLAlchemyIndustryInventoryRepository(session)
        )
        .execute(
            AnalyzeIndustryInventoryRequest(
                industry_id=industry.id or 0,
                aggregate_region_code="WORLD",
                requested_scope=scope,
                source_id=source.id,
                as_of=CUTOFF,
                config=_config(),
            )
        )
        .snapshot
    )
    assert result.production_value == Decimal("50.000000000000")
    assert result.shipments_value is None
    assert result.production_shipment_gap is None
    assert any("matching period" in reason for reason in result.unavailable_reasons)


@pytest.mark.parametrize(
    ("overrides", "expected_role", "expected_region_codes"),
    [
        (
            {date(2024, 12, 31): ("JP",)},
            "YEAR_PRIOR_INVENTORY",
            ("JP",),
        ),
        (
            {date(2024, 12, 31): ("US",)},
            "YEAR_PRIOR_INVENTORY",
            ("US",),
        ),
        (
            {
                date(2023, 12, 31): ("JP",),
                date(2024, 12, 31): ("US",),
            },
            "PRIOR_YEAR_PRIOR_INVENTORY",
            ("JP",),
        ),
    ],
)
def test_incompatible_historical_inventory_composition_is_audited_and_not_compared(
    session: Session,
    overrides: dict[date, tuple[str, ...]],
    expected_role: str,
    expected_region_codes: tuple[str, ...],
) -> None:
    aggregate_repo, industry, source, scope = _aggregate_series(
        session, inventory_region_overrides=overrides
    )
    result = (
        AnalyzeIndustryInventory(
            aggregate_repo, SQLAlchemyIndustryInventoryRepository(session)
        )
        .execute(
            AnalyzeIndustryInventoryRequest(
                industry_id=industry.id or 0,
                aggregate_region_code="WORLD",
                requested_scope=scope,
                source_id=source.id,
                as_of=CUTOFF,
                config=_config(Decimal("0.40")),
            )
        )
        .snapshot
    )

    assert result.yoy_growth is None
    assert result.status is IndustryInventoryStatus.INSUFFICIENT_DATA
    ref = next(item for item in result.input_references if item.role == expected_role)
    assert not ref.included
    assert (
        tuple(code for _region_id, code in ref.contributing_regions)
        == expected_region_codes
    )
    assert ref.coverage == Decimal("0.5000000")
    assert ref.exclusion_reason is not None
    assert "actual contributing regions differ" in ref.exclusion_reason
    assert result.classification is IndustryInventoryClassification.UNKNOWN


def test_current_and_previous_inventory_with_different_regions_are_not_compared(
    session: Session,
) -> None:
    aggregate_repo, industry, source, scope = _aggregate_series(
        session,
        inventory_region_overrides={date(2024, 12, 31): ("JP",)},
    )
    result = (
        AnalyzeIndustryInventory(
            aggregate_repo, SQLAlchemyIndustryInventoryRepository(session)
        )
        .execute(
            AnalyzeIndustryInventoryRequest(
                industry_id=industry.id or 0,
                aggregate_region_code="WORLD",
                requested_scope=scope,
                source_id=source.id,
                as_of=CUTOFF,
                config=_config(Decimal("0.40")),
            )
        )
        .snapshot
    )
    assert result.prior_inventory_value is None
    assert result.absolute_change is None
    assert result.trend is IndustryInventoryTrend.UNKNOWN
    assert any(
        "Previous inventory excluded" in reason for reason in result.unavailable_reasons
    )


def test_production_and_shipments_require_identical_actual_regions(
    session: Session,
) -> None:
    aggregate_repo, industry, source, scope = _aggregate_series(
        session,
        flow_region_overrides={
            IndustrySignalType.PRODUCTION: ("JP", "US"),
            IndustrySignalType.SHIPMENTS: ("JP",),
        },
    )
    result = (
        AnalyzeIndustryInventory(
            aggregate_repo, SQLAlchemyIndustryInventoryRepository(session)
        )
        .execute(
            AnalyzeIndustryInventoryRequest(
                industry_id=industry.id or 0,
                aggregate_region_code="WORLD",
                requested_scope=scope,
                source_id=source.id,
                as_of=CUTOFF,
                config=_config(),
            )
        )
        .snapshot
    )
    assert result.production_shipment_gap is None
    shipment = next(ref for ref in result.input_references if ref.role == "SHIPMENTS")
    assert not shipment.included
    assert tuple(code for _region_id, code in shipment.contributing_regions) == ("JP",)
    assert "actual contributing regions differ" in (shipment.exclusion_reason or "")


def test_historical_partial_coverage_cannot_become_available_from_full_current_coverage(
    session: Session,
) -> None:
    aggregate_repo, industry, source, scope = _aggregate_series(
        session,
        inventory_region_overrides={date(2024, 12, 31): ("JP",)},
    )
    result = (
        AnalyzeIndustryInventory(
            aggregate_repo, SQLAlchemyIndustryInventoryRepository(session)
        )
        .execute(
            AnalyzeIndustryInventoryRequest(
                industry_id=industry.id or 0,
                aggregate_region_code="WORLD",
                requested_scope=scope,
                source_id=source.id,
                as_of=CUTOFF,
                config=_config(Decimal("0.40")),
            )
        )
        .snapshot
    )
    assert result.coverage == Decimal("1.0000000")
    assert result.yoy_growth is None
    assert result.status is IndustryInventoryStatus.INSUFFICIENT_DATA
    assert result.classification is IndustryInventoryClassification.UNKNOWN


def test_engine_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    database = tmp_path / "industry_inventory_migration.db"
    config = Config(str(Path.cwd() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database}")
    command.upgrade(config, "0024_industry_signal_aggregate_scopes")
    legacy_engine = create_database_engine(f"sqlite:///{database}")
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO industries "
            "(code, name, is_active, created_at, updated_at) "
            "VALUES ('LEGACY', 'Legacy industry', 1, CURRENT_TIMESTAMP, "
            "CURRENT_TIMESTAMP)"
        )
    legacy_engine.dispose()
    command.upgrade(config, "0025_industry_inventory_engine")
    command.upgrade(config, "0026_industry_inventory_input_composition")
    engine = create_database_engine(f"sqlite:///{database}")
    assert "industry_inventory_snapshots" in inspect(engine).get_table_names()
    assert "industry_inventory_inputs" in inspect(engine).get_table_names()
    assert "industry_inventory_scopes" in inspect(engine).get_table_names()
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("industry_inventory_inputs")
    }
    assert {
        "contributing_regions",
        "coverage",
        "included",
        "exclusion_reason",
    } <= columns
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT name FROM industries WHERE code = 'LEGACY'"
            ).scalar_one()
            == "Legacy industry"
        )
    command.downgrade(config, "0025_industry_inventory_engine")
    legacy_columns = {
        column["name"]
        for column in inspect(engine).get_columns("industry_inventory_inputs")
    }
    assert (
        not {
            "contributing_regions",
            "coverage",
            "included",
            "exclusion_reason",
        }
        & legacy_columns
    )
    command.downgrade(config, "0024_industry_signal_aggregate_scopes")
    assert "industry_inventory_snapshots" not in inspect(engine).get_table_names()
    assert "industry_inventory_inputs" not in inspect(engine).get_table_names()
    assert "industry_inventory_scopes" not in inspect(engine).get_table_names()
    engine.dispose()


def test_explicit_source_does_not_fall_back_to_other_cohort(session: Session) -> None:
    aggregate_repo, industry, source, scope = _aggregate_series(session)
    with pytest.raises(DomainValidationError, match="No eligible industry inventory"):
        AnalyzeIndustryInventory(
            aggregate_repo, SQLAlchemyIndustryInventoryRepository(session)
        ).execute(
            AnalyzeIndustryInventoryRequest(
                industry_id=industry.id or 0,
                aggregate_region_code="WORLD",
                requested_scope=scope,
                source_id=(source.id or 0) + 100,
                as_of=CUTOFF,
                config=_config(),
            )
        )


def test_region_scope_identity_must_match_the_requested_codes(session: Session) -> None:
    aggregate_repo, industry, source, scope = _aggregate_series(session)
    wrong_scope = tuple(sorted(((scope[0][0], "US"), (scope[1][0], "JP"))))
    with pytest.raises(DomainValidationError, match="No eligible industry inventory"):
        AnalyzeIndustryInventory(
            aggregate_repo, SQLAlchemyIndustryInventoryRepository(session)
        ).execute(
            AnalyzeIndustryInventoryRequest(
                industry_id=industry.id or 0,
                aggregate_region_code="WORLD",
                requested_scope=wrong_scope,
                source_id=source.id,
                as_of=CUTOFF,
                config=_config(),
            )
        )
