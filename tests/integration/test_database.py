"""Database integrity and repository tests."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cyclescope.domain.entities import (
    Company,
    DataSource,
    Industry,
    Security,
    SubIndustry,
)
from cyclescope.infrastructure.database.initialize import (
    INITIAL_INDUSTRIES,
    seed_industries,
)
from cyclescope.infrastructure.database.models import (
    CompanyIndustryExposureModel,
    CompanyModel,
    IndustryModel,
    SubIndustryModel,
)
from cyclescope.infrastructure.database.repositories.master_data import (
    CompanySqlAlchemyRepository,
    DataSourceSqlAlchemyRepository,
    IndustrySqlAlchemyRepository,
    SecuritySqlAlchemyRepository,
    SubIndustrySqlAlchemyRepository,
)
from cyclescope.infrastructure.database.session import (
    create_database_engine,
    create_session_factory,
    transaction,
)


def test_seed_is_repeatable(session: Session) -> None:
    seed_industries(session)
    session.commit()
    seed_industries(session)
    session.commit()
    assert session.query(IndustryModel).count() == 7


def test_alembic_initialization_is_repeatable(tmp_path: object) -> None:
    """Seed a migrated database repeatedly without overwriting master data."""
    database_path = tmp_path / "migration.db"  # type: ignore[operator]
    config = Config(str(Path.cwd() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    engine = create_database_engine(f"sqlite:///{database_path}")
    factory = create_session_factory(engine)
    with factory.begin() as session:
        assert session.query(IndustryModel).count() == 0
        session.add(IndustryModel(code="STEEL", name="User's steel label"))
        session.add(IndustryModel(code="CUSTOM", name="Custom industry"))
    with factory.begin() as session:
        seed_industries(session)
    with factory.begin() as session:
        seed_industries(session)
        steel = session.query(IndustryModel).filter_by(code="STEEL").one()
        assert steel.name == "User's steel label"
        assert session.query(IndustryModel).count() == len(INITIAL_INDUSTRIES) + 1
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one()
            == "0010_anomaly_optimistic_lock"
        )
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        assert (
            connection.exec_driver_sql(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='data_anomaly_lifecycle_events'"
            ).scalar_one()
            == "data_anomaly_lifecycle_events"
        )
        version_column = next(
            row
            for row in connection.exec_driver_sql("PRAGMA table_info(data_anomalies)")
            if row[1] == "version_id"
        )
        assert version_column[3] == 1 and version_column[4] == "1"
    engine.dispose()


def test_repository_crud(session: Session) -> None:
    repository = IndustrySqlAlchemyRepository(session)
    created = repository.create(Industry(code="STEEL", name="Steel"))
    session.commit()
    assert isinstance(created, Industry)
    assert created.created_at is not None and created.created_at.utcoffset() is not None
    assert repository.get_by_id(created.id or 0) == created
    assert repository.list()[0] == created
    updated = repository.update(replace(created, name="Steel & Iron"))
    assert updated is not None and updated.name == "Steel & Iron"
    assert updated.updated_at is not None
    assert created.updated_at is not None and updated.updated_at >= created.updated_at
    assert repository.delete(created.id or 0)
    assert repository.get_by_id(created.id or 0) is None
    assert repository.update(Industry(code="MISSING", name="Missing")) is None
    assert not repository.delete(created.id or 0)
    with pytest.raises(ValueError):
        repository.list(limit=0)


def test_each_master_repository_maps_to_domain_entities(session: Session) -> None:
    """Ensure no SQLAlchemy model escapes any master-data repository."""
    industry = IndustrySqlAlchemyRepository(session).create(
        Industry(code="STEEL", name="Steel")
    )
    sub_industry = SubIndustrySqlAlchemyRepository(session).create(
        SubIndustry(industry_id=industry.id or 0, code="FLAT", name="Flat steel")
    )
    company = CompanySqlAlchemyRepository(session).create(
        Company(name="Example Co", country_code="JP")
    )
    security = SecuritySqlAlchemyRepository(session).create(
        Security(
            company_id=company.id or 0,
            security_type="common_stock",
        )
    )
    source = DataSourceSqlAlchemyRepository(session).create(
        DataSource(code="EXAMPLE", name="Example", provider_type="manual")
    )
    assert isinstance(industry, Industry)
    assert isinstance(sub_industry, SubIndustry)
    assert isinstance(company, Company)
    assert isinstance(security, Security)
    assert isinstance(source, DataSource)
    assert isinstance(
        SecuritySqlAlchemyRepository(session).get_by_id(security.id or 0), Security
    )


def test_transaction_context_commits_and_rolls_back(tmp_path: object) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'transaction.db'}")  # type: ignore[operator]
    from cyclescope.infrastructure.database.base import Base

    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with transaction(factory) as db_session:
        db_session.add(IndustryModel(code="COMMITTED", name="Committed"))
    with pytest.raises(RuntimeError):
        with transaction(factory) as db_session:
            db_session.add(IndustryModel(code="ROLLED_BACK", name="Rolled back"))
            raise RuntimeError("abort transaction")
    with factory() as db_session:
        assert db_session.query(IndustryModel).count() == 1
    engine.dispose()


def test_foreign_keys_and_exposure_share_are_enforced(session: Session) -> None:
    session.add(SubIndustryModel(industry_id=999, code="BAD", name="Bad"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    industry = IndustryModel(code="STEEL", name="Steel")
    company = CompanyModel(name="Example", country_code="JP")
    session.add_all([industry, company])
    session.flush()
    sub = SubIndustryModel(industry_id=industry.id, code="FLAT", name="Flat steel")
    session.add(sub)
    session.flush()
    session.add(
        CompanyIndustryExposureModel(
            company_id=company.id, sub_industry_id=sub.id, revenue_share=Decimal("1.2")
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_transaction_rollback(session: Session) -> None:
    session.add(IndustryModel(code="ROLLBACK", name="Rollback"))
    session.rollback()
    assert session.query(IndustryModel).count() == 0
