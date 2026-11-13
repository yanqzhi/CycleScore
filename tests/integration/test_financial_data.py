from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from cyclescope.application.use_cases.financial_data import (
    FinancialLineInput,
    GetFinancialStatementAsOf,
    GetFinancialStatements,
    ImportFinancialStatement,
    ImportFinancialStatementInput,
)
from cyclescope.domain.entities.financial_data import (
    FinancialItem,
    FinancialItemMapping,
    FinancialStatement,
    FinancialStatementItem,
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
    FinancialItemModel,
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


def test_available_at_cannot_precede_known_publication_instant():
    with pytest.raises(DomainValidationError, match="available_at"):
        FinancialStatement(
            1,
            1,
            StatementType.BS,
            "IFRS",
            ConsolidationScope.CONSOLIDATED,
            2026,
            FiscalPeriod.FY,
            None,
            date(2026, 3, 31),
            date(2026, 5, 15),
            datetime(2026, 5, 15, 17, tzinfo=UTC),
            datetime(2026, 5, 15, 16, tzinfo=UTC),
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
    stored_item = session.get(FinancialItemModel, item.id)
    assert stored_item is not None
    stored_item.is_active = False
    session.flush()
    query = GetFinancialStatements(statements, lines)
    before = query.execute(
        company.id, NOW + timedelta(days=1), statement_type=StatementType.PL
    )
    assert {(x.statement.source_id, x.items[0].value) for x in before} == {
        (source1.id, Decimal("100")),
        (source2.id, Decimal("101")),
    }
    same_instant_utc = query.execute(
        company.id,
        datetime(2026, 5, 15, 16, tzinfo=UTC),
        statement_type=StatementType.PL,
    )
    same_instant_jst = query.execute(
        company.id,
        datetime(2026, 5, 16, 1, tzinfo=timezone(timedelta(hours=9))),
        statement_type=StatementType.PL,
    )
    assert [(x.statement.id, x.items[0].value) for x in same_instant_utc] == [
        (x.statement.id, x.items[0].value) for x in same_instant_jst
    ]
    earlier_non_utc = query.execute(
        company.id,
        datetime(2026, 5, 16, 0, 59, tzinfo=timezone(timedelta(hours=9))),
        statement_type=StatementType.PL,
    )
    assert all(x.statement.source_id != source1.id for x in earlier_non_utc)
    later_non_utc = query.execute(
        company.id,
        datetime(2026, 5, 16, 2, tzinfo=timezone(timedelta(hours=9))),
        statement_type=StatementType.PL,
    )
    assert any(
        x.statement.source_id == source1.id and x.items[0].value == Decimal("100")
        for x in later_non_utc
    )
    after = query.execute(
        company.id, NOW + timedelta(days=3), statement_type=StatementType.PL
    )
    assert {(x.statement.source_id, x.items[0].value) for x in after} == {
        (source1.id, Decimal("90")),
        (source2.id, Decimal("101")),
    }
    point_query = GetFinancialStatementAsOf(query)
    selected = point_query.execute(
        company.id, StatementType.PL, 2026, FiscalPeriod.Q1, NOW, source_id=source1.id
    )
    assert selected is not None and selected.items[0].value == Decimal("100")
    selected_later = point_query.execute(
        company.id,
        StatementType.PL,
        2026,
        FiscalPeriod.Q1,
        NOW + timedelta(days=3),
        source_id=source1.id,
    )
    assert selected_later is not None and selected_later.items[0].value == Decimal("90")
    assert (
        point_query.execute(
            company.id,
            StatementType.PL,
            2025,
            FiscalPeriod.FY,
            NOW,
            source_id=source1.id,
        )
        is None
    )
    with pytest.raises(DomainValidationError, match="source_id is required"):
        point_query.execute(company.id, StatementType.PL, 2026, FiscalPeriod.Q1, NOW)
    stored_item.is_active = True
    session.flush()
    ambiguous_period = replace(
        request(source1.id, 1, NOW, NOW, Decimal("102")),
        period_start=date(2026, 4, 1),
        period_end=date(2026, 6, 30),
    )
    importer.execute(ambiguous_period)
    stored_item.is_active = False
    session.flush()
    with pytest.raises(DomainValidationError, match="ambiguous"):
        point_query.execute(
            company.id,
            StatementType.PL,
            2026,
            FiscalPeriod.Q1,
            NOW,
            source_id=source1.id,
        )
    inactive = FinancialItem(
        "INACTIVE",
        "Inactive",
        StatementType.PL,
        "income",
        UnitDimension.CURRENCY_AMOUNT,
        is_active=False,
    )
    inactive = items.create(inactive)
    with pytest.raises(DomainValidationError, match="inactive"):
        importer.execute(
            replace(
                request(source1.id, 3, NOW + timedelta(days=3), NOW, Decimal("1")),
                items=(
                    FinancialLineInput(inactive.id, Decimal("1"), "CURRENCY", 1, "USD"),
                ),
            )
        )
    assert query.execute(company.id, NOW + timedelta(days=3), source_id=source1.id)


@pytest.mark.parametrize(
    ("value", "should_be_valid"),
    [
        (Decimal("1E+25"), True),
        (Decimal("1E+26"), False),
        (Decimal("1E+30"), False),
        (Decimal("0.000000000001"), True),
        (Decimal("0.0000000000001"), False),
        (Decimal("-1E+25"), True),
        (Decimal("-1E+26"), False),
    ],
)
def test_numeric_38_12_precision_boundaries(
    value: Decimal, should_be_valid: bool
) -> None:
    statement = FinancialStatement(
        1,
        1,
        StatementType.PL,
        "IFRS",
        ConsolidationScope.CONSOLIDATED,
        2026,
        FiscalPeriod.Q1,
        date(2026, 1, 1),
        date(2026, 3, 31),
        date(2026, 5, 15),
        None,
        NOW,
        NOW,
        1,
        "USD",
    )
    item = FinancialItem(
        "REVENUE", "Revenue", StatementType.PL, "income", UnitDimension.CURRENCY_AMOUNT
    )
    line = FinancialStatementItem(1, 1, value, "USD", "CURRENCY", 1)
    if should_be_valid:
        line.validate_for(item, statement)
    else:
        with pytest.raises(DomainValidationError, match=r"NUMERIC\(38, 12\)"):
            line.validate_for(item, statement)


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
    assert "ck_financial_statements_fiscal_period" in {
        row["name"]
        for row in inspect(engine).get_check_constraints("financial_statements")
    }
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
