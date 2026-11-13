"""Database integrity and repository tests."""

from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cyclescope.infrastructure.database.initialize import seed_industries
from cyclescope.infrastructure.database.models import (
    CompanyIndustryExposureModel,
    CompanyModel,
    IndustryModel,
    SubIndustryModel,
)
from cyclescope.infrastructure.database.repositories.master_data import (
    IndustrySqlAlchemyRepository,
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
    """Apply the actual migration twice and retain a single versioned schema."""
    database_path = tmp_path / "migration.db"  # type: ignore[operator]
    config = Config(str(Path.cwd() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    engine = create_database_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one()
            == "0001_master_data"
        )
        assert (
            connection.exec_driver_sql("SELECT COUNT(*) FROM industries").scalar_one()
            == 0
        )
    engine.dispose()


def test_repository_crud(session: Session) -> None:
    repository = IndustrySqlAlchemyRepository(session)
    created = repository.create({"code": "STEEL", "name": "Steel"})
    session.commit()
    assert repository.get_by_id(created["id"]) == created
    assert created["created_at"].tzinfo is not None
    assert repository.list()[0]["code"] == "STEEL"
    updated = repository.update(created["id"], {"name": "Steel & Iron"})
    assert updated is not None and updated["name"] == "Steel & Iron"
    assert repository.delete(created["id"])
    assert repository.get_by_id(created["id"]) is None
    assert repository.update(created["id"], {"name": "missing"}) is None
    assert not repository.delete(created["id"])
    with pytest.raises(ValueError):
        repository.list(limit=0)


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
