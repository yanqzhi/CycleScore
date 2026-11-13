from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from cyclescope.application.use_cases.financial_data import (
    FinancialLineInput,
    GetFinancialStatements,
    ImportFinancialStatement,
    ImportFinancialStatementInput,
)
from cyclescope.domain.entities.financial_data import (
    FinancialItem,
    FinancialItemMapping,
    FinancialStatement,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.financial_data import (
    ConsolidationScope,
    FiscalPeriod,
    StatementType,
    UnitDimension,
    validate_item_unit,
)
from cyclescope.infrastructure.database.models import CompanyModel, DataSourceModel
from cyclescope.infrastructure.database.models.financial_data import (
    FinancialStatementModel,
)
from cyclescope.infrastructure.database.repositories.financial_data import (
    SQLAlchemyFinancialItemMappingRepository,
    SQLAlchemyFinancialItemRepository,
    SQLAlchemyFinancialStatementItemRepository,
    SQLAlchemyFinancialStatementRepository,
)
from cyclescope.infrastructure.database.repositories.master_data import (
    CompanySqlAlchemyRepository,
    DataSourceSqlAlchemyRepository,
)
from cyclescope.infrastructure.database.session import create_database_engine

NOW = datetime(2026, 5, 15, 16, tzinfo=UTC)


def test_statement_domain_validates_time_and_period():
    with pytest.raises(DomainValidationError):
        FinancialStatement(
            1,
            1,
            StatementType.PL,
            "IFRS",
            ConsolidationScope.CONSOLIDATED,
            2026,
            FiscalPeriod.Q1,
            None,
            date(2026, 3, 31),
            date(2026, 5, 15),
            None,
            NOW,
            NOW,
            1,
            "USD",
        )
    with pytest.raises(DomainValidationError):
        FinancialStatement(
            1,
            1,
            StatementType.BS,
            "IFRS",
            ConsolidationScope.CONSOLIDATED,
            2026,
            FiscalPeriod.FY,
            None,
            date(2026, 12, 31),
            date(2027, 2, 1),
            None,
            datetime(2027, 2, 1),
            NOW,
            1,
            "USD",
        )


def test_unit_validation_accepts_non_currency_and_rejects_bad_dimension():
    validate_item_unit(UnitDimension.SHARES, "SHARES", None)
    with pytest.raises(DomainValidationError):
        validate_item_unit(UnitDimension.CURRENCY_AMOUNT, "SHARES", None)


def test_financial_statement_import_is_as_of_and_source_scoped(session):
    company = CompanyModel(name="Issuer", country_code="JP")
    source1 = DataSourceModel(code="SRC1", name="Source 1", provider_type="test")
    source2 = DataSourceModel(code="SRC2", name="Source 2", provider_type="test")
    session.add_all([company, source1, source2])
    session.flush()
    items = SQLAlchemyFinancialItemRepository(session)
    item = items.create(
        FinancialItem(
            "REVENUE",
            "Revenue",
            StatementType.PL,
            "income",
            UnitDimension.CURRENCY_AMOUNT,
        )
    )
    company_repo = CompanySqlAlchemyRepository(session)
    source_repo = DataSourceSqlAlchemyRepository(session)
    statements = SQLAlchemyFinancialStatementRepository(session)
    lines = SQLAlchemyFinancialStatementItemRepository(session)
    importer = ImportFinancialStatement(
        statements, lines, items, company_repo, source_repo
    )

    def request(src, rev, available, collected, value):
        return ImportFinancialStatementInput(
            company.id,
            src,
            StatementType.PL,
            "IFRS",
            ConsolidationScope.CONSOLIDATED,
            2026,
            FiscalPeriod.Q1,
            date(2026, 1, 1),
            date(2026, 3, 31),
            date(2026, 5, 15),
            None,
            available,
            collected,
            rev,
            "USD",
            (FinancialLineInput(item.id, value, "CURRENCY", 1, "USD"),),
        )

    invalid = request(source1.id, 1, NOW, NOW, Decimal("100"))
    invalid = replace(
        invalid,
        items=(FinancialLineInput(99999, Decimal("2"), "CURRENCY", 1, "USD"),),
    )
    with pytest.raises(DomainValidationError):
        importer.execute(invalid)
    assert session.query(FinancialStatementModel).count() == 0
    importer.execute(
        request(source1.id, 1, NOW, NOW + timedelta(minutes=10), Decimal("100"))
    )
    importer.execute(
        request(
            source1.id,
            2,
            NOW + timedelta(days=2),
            NOW + timedelta(days=2),
            Decimal("90"),
        )
    )
    importer.execute(request(source2.id, 1, NOW, NOW, Decimal("101")))
    query = GetFinancialStatements(statements, lines)
    before = query.execute(
        company.id, NOW + timedelta(days=1), statement_type=StatementType.PL
    )
    assert {(x.statement.source_id, x.items[0].value) for x in before} == {
        (source1.id, Decimal("100")),
        (source2.id, Decimal("101")),
    }
    after = query.execute(
        company.id, NOW + timedelta(days=3), statement_type=StatementType.PL
    )
    assert {(x.statement.source_id, x.items[0].value) for x in after} == {
        (source1.id, Decimal("90")),
        (source2.id, Decimal("101")),
    }


def test_financial_migration_downgrade_and_reupgrade_preserve_existing_rows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "migration_cycle.db"
    config = Config(str(Path.cwd() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "0004_security_listing_normalization")
    engine = create_database_engine(f"sqlite:///{path}")
    with Session(engine) as session:
        session.add(CompanyModel(name="Existing issuer", country_code="JP"))
        session.commit()
    command.upgrade(config, "head")
    assert {
        "financial_items",
        "financial_statements",
        "financial_statement_items",
        "financial_item_mappings",
    } <= set(inspect(engine).get_table_names())
    command.downgrade(config, "0004_security_listing_normalization")
    assert not (
        {
            "financial_items",
            "financial_statements",
            "financial_statement_items",
            "financial_item_mappings",
        }
        & set(inspect(engine).get_table_names())
    )
    with Session(engine) as session:
        assert session.query(CompanyModel).count() == 1
    command.upgrade(config, "head")
    assert {
        "financial_items",
        "financial_statements",
        "financial_statement_items",
        "financial_item_mappings",
    } <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_source_item_mapping_prefers_standard_then_uses_default(session):
    source = DataSourceModel(code="MAPSRC", name="Mapping source", provider_type="test")
    session.add(source)
    session.flush()
    items = SQLAlchemyFinancialItemRepository(session)
    revenue = items.create(
        FinancialItem(
            "REV", "Revenue", StatementType.PL, "income", UnitDimension.CURRENCY_AMOUNT
        )
    )
    earnings = items.create(
        FinancialItem(
            "EARN",
            "Earnings",
            StatementType.PL,
            "income",
            UnitDimension.CURRENCY_AMOUNT,
        )
    )
    mappings = SQLAlchemyFinancialItemMappingRepository(session)
    mappings.create(FinancialItemMapping(source.id, "X1", "Generic", revenue.id))
    mappings.create(
        FinancialItemMapping(source.id, "X1", "IFRS variant", earnings.id, "IFRS")
    )
    assert (
        mappings.resolve_source_item(source.id, "X1", "IFRS").financial_item_id
        == earnings.id
    )
    assert (
        mappings.resolve_source_item(source.id, "X1", "US_GAAP").financial_item_id
        == revenue.id
    )
    assert mappings.resolve_source_item(source.id, "X1").financial_item_id == revenue.id
