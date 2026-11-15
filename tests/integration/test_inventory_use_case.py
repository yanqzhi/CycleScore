"""SQLite integration tests for inventory PIT calculation and persistence."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from cyclescope.application.dto.inventory import CalculateInventoryRequest
from cyclescope.application.use_cases.financial_data import GetFinancialStatements
from cyclescope.application.use_cases.inventory import CalculateInventory
from cyclescope.domain.entities.financial_data import FinancialItem
from cyclescope.domain.entities.inventory import InventoryStatus, InventoryTrend
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.financial_data import StatementType, UnitDimension
from cyclescope.infrastructure.database.models import (
    CompanyModel,
    DataSourceModel,
    FinancialStatementItemModel,
    FinancialStatementModel,
)
from cyclescope.infrastructure.database.repositories.financial_data import (
    SQLAlchemyFinancialItemRepository,
    SQLAlchemyFinancialStatementItemRepository,
    SQLAlchemyFinancialStatementRepository,
)
from cyclescope.infrastructure.database.repositories.inventory import (
    SQLAlchemyInventorySnapshotRepository,
)

AS_OF = datetime(2026, 6, 1, 12, tzinfo=UTC)


def _statement(
    session: Session,
    *,
    company_id: int,
    source_id: int,
    year: int,
    statement_type: str,
    currency: str = "JPY",
    standard: str = "JGAAP",
    scope: str = "CONSOLIDATED",
    period_start: date | None = None,
    period_end: date | None = None,
    revision: int = 1,
    available_at: datetime | None = None,
) -> FinancialStatementModel:
    end = period_end or date(year + 1, 3, 31)
    start = (
        period_start
        if period_start is not None
        else date(year, 4, 1)
        if statement_type == "PL"
        else None
    )
    available = available_at or datetime(
        end.year, end.month, end.day, tzinfo=UTC
    ) + timedelta(days=60)
    row = FinancialStatementModel(
        company_id=company_id,
        source_id=source_id,
        statement_type=statement_type,
        accounting_standard=standard,
        consolidation_scope=scope,
        fiscal_year=year,
        fiscal_period="FY",
        period_start=start,
        period_end=end,
        publication_date=available.date(),
        publication_datetime=available,
        available_at=available,
        collected_at=available + timedelta(days=1),
        revision_number=revision,
        reporting_currency=currency,
    )
    session.add(row)
    session.flush()
    return row


def _insert_year(
    session: Session,
    company_id: int,
    source_id: int,
    items: dict[str, int],
    year: int,
    inventory: str,
    cogs: str,
    *,
    revision: int = 1,
    bs_currency: str = "JPY",
    pl_currency: str = "JPY",
    bs_standard: str = "JGAAP",
    pl_standard: str = "JGAAP",
    bs_scope: str = "CONSOLIDATED",
    pl_scope: str = "CONSOLIDATED",
    pl_period_end: date | None = None,
    bs_period_start: date | None = None,
    available_at: datetime | None = None,
) -> tuple[FinancialStatementModel, FinancialStatementModel]:
    balance = _statement(
        session,
        company_id=company_id,
        source_id=source_id,
        year=year,
        statement_type="BS",
        currency=bs_currency,
        standard=bs_standard,
        scope=bs_scope,
        period_start=bs_period_start,
        revision=revision,
        available_at=available_at,
    )
    income = _statement(
        session,
        company_id=company_id,
        source_id=source_id,
        year=year,
        statement_type="PL",
        currency=pl_currency,
        standard=pl_standard,
        scope=pl_scope,
        period_end=pl_period_end,
        revision=revision,
        available_at=available_at,
    )
    session.add_all(
        [
            FinancialStatementItemModel(
                financial_statement_id=balance.id,
                financial_item_id=items["INVENTORIES"],
                value=Decimal(inventory),
                currency_code=bs_currency,
                unit_code="CURRENCY",
                scale_multiplier=1,
            ),
            FinancialStatementItemModel(
                financial_statement_id=income.id,
                financial_item_id=items["COST_OF_GOODS_SOLD"],
                value=Decimal(cogs),
                currency_code=pl_currency,
                unit_code="CURRENCY",
                scale_multiplier=1,
            ),
        ]
    )
    session.flush()
    return balance, income


def _insert_bs_only(
    session: Session,
    company_id: int,
    source_id: int,
    inventory_item_id: int,
    fiscal_year: int,
    period_start: date,
    period_end: date,
    value: str,
) -> FinancialStatementModel:
    statement = _statement(
        session,
        company_id=company_id,
        source_id=source_id,
        year=fiscal_year,
        statement_type="BS",
        period_start=period_start,
        period_end=period_end,
    )
    session.add(
        FinancialStatementItemModel(
            financial_statement_id=statement.id,
            financial_item_id=inventory_item_id,
            value=Decimal(value),
            currency_code="JPY",
            unit_code="CURRENCY",
            scale_multiplier=1,
        )
    )
    session.flush()
    return statement


def _setup(session: Session, *, years=(2022, 2023, 2024, 2025)):
    company = CompanyModel(name="Inventory Co", country_code="JP")
    source = DataSourceModel(
        code="INV_PRIMARY", name="Inventory Primary", provider_type="test"
    )
    session.add_all([company, source])
    session.flush()
    item_repo = SQLAlchemyFinancialItemRepository(session)
    items = {
        "INVENTORIES": item_repo.create(
            FinancialItem(
                "INVENTORIES",
                "Inventories",
                StatementType.BS,
                "assets",
                UnitDimension.CURRENCY_AMOUNT,
            )
        ).id,
        "COST_OF_GOODS_SOLD": item_repo.create(
            FinancialItem(
                "COST_OF_GOODS_SOLD",
                "Cost of goods sold",
                StatementType.PL,
                "costs",
                UnitDimension.CURRENCY_AMOUNT,
            )
        ).id,
    }
    for year in years:
        _insert_year(
            session, company.id, source.id, items, year, str((year - 2021) * 20), "500"
        )
    query = GetFinancialStatements(
        SQLAlchemyFinancialStatementRepository(session),
        SQLAlchemyFinancialStatementItemRepository(session),
    )
    repository = SQLAlchemyInventorySnapshotRepository(session)
    calculator = CalculateInventory(query, item_repo, repository)
    return calculator, repository, company, source, items


def test_inventory_pit_revision_and_repository_round_trip(session: Session) -> None:
    calculator, repository, company, source, items = _setup(session)
    _insert_year(
        session,
        company.id,
        source.id,
        items,
        2024,
        "999",
        "999",
        revision=2,
        available_at=AS_OF + timedelta(days=20),
    )
    result = calculator.execute(CalculateInventoryRequest(company.id, AS_OF))
    current = result.snapshots[-1]
    assert current.fiscal_year == 2025
    assert current.closing_inventory == Decimal("80")
    assert current.inventory_turnover == (Decimal("500") / Decimal("70")).quantize(
        Decimal("0.000000000001")
    )
    assert current.dio is not None and current.dio > 0
    assert current.trend == InventoryTrend.INCREASING
    assert all(
        reference.available_at <= AS_OF for reference in current.input_references
    )
    assert all(reference.revision_number == 1 for reference in current.input_references)
    assert repository.list_by_company(company.id) == list(result.snapshots)


def test_inventory_multiple_sources_are_ambiguous(session: Session) -> None:
    calculator, _, company, _, items = _setup(session, years=(2024,))
    second = DataSourceModel(code="INV_SECOND", name="Other", provider_type="test")
    session.add(second)
    session.flush()
    _insert_year(session, company.id, second.id, items, 2024, "50", "400")
    with pytest.raises(DomainValidationError, match="financial_source_id is required"):
        calculator.execute(CalculateInventoryRequest(company.id, AS_OF))


def test_explicit_source_selection_uses_only_requested_source(session: Session) -> None:
    calculator, _, company, source, items = _setup(session, years=(2024,))
    second = DataSourceModel(code="INV_SECOND", name="Other", provider_type="test")
    session.add(second)
    session.flush()
    _insert_year(session, company.id, second.id, items, 2024, "50", "400")
    result = calculator.execute(
        CalculateInventoryRequest(company.id, AS_OF, financial_source_id=source.id)
    )
    assert len(result.snapshots) == 1
    assert result.snapshots[0].source_id == source.id
    assert {ref.source_id for ref in result.snapshots[0].input_references} == {
        source.id
    }


def test_no_pit_visible_annual_data_is_explicitly_unavailable(session: Session) -> None:
    calculator, repository, company, _, _ = _setup(session, years=())
    result = calculator.execute(CalculateInventoryRequest(company.id, AS_OF))
    assert result.snapshots == ()
    assert result.status == InventoryStatus.UNAVAILABLE
    assert result.unavailable_reason == "No PIT-visible annual FY financial statements."
    assert repository.list_by_company(company.id) == []


def test_currency_mismatch_is_fatal_and_period_mismatch_is_unavailable(
    session: Session,
) -> None:
    calculator, repository, company, source, items = _setup(session, years=())
    _insert_year(
        session,
        company.id,
        source.id,
        items,
        2024,
        "10",
        "100",
        bs_currency="JPY",
        pl_currency="USD",
    )
    with pytest.raises(DomainValidationError, match="incompatible"):
        calculator.execute(CalculateInventoryRequest(company.id, AS_OF))
    session.rollback()
    session.expire_all()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"pl_standard": "IFRS"}, "standard"),
        ({"pl_scope": "NON_CONSOLIDATED"}, "scope"),
    ],
)
def test_accounting_basis_mismatch_is_fatal(session, overrides, message) -> None:
    calculator, _, company, source, items = _setup(session, years=())
    _insert_year(session, company.id, source.id, items, 2024, "10", "100", **overrides)
    with pytest.raises(DomainValidationError, match="incompatible"):
        calculator.execute(CalculateInventoryRequest(company.id, AS_OF))


def test_incompatible_fiscal_period_has_explicit_reason(session: Session) -> None:
    calculator, _, company, _, items = _setup(session, years=())
    source = session.query(DataSourceModel).filter_by(code="INV_PRIMARY").one()
    _insert_year(
        session,
        company.id,
        source.id,
        items,
        2024,
        "10",
        "100",
        pl_period_end=date(2025, 2, 28),
    )
    result = calculator.execute(CalculateInventoryRequest(company.id, AS_OF))
    snapshot = result.snapshots[0]
    assert snapshot.cogs is None
    assert any("periods" in reason for reason in snapshot.unavailable_reasons)
    assert snapshot.status == InventoryStatus.PARTIAL


def test_bs_and_pl_period_starts_must_match_when_both_are_present(
    session: Session,
) -> None:
    calculator, _, company, source, items = _setup(session, years=())
    _insert_year(
        session,
        company.id,
        source.id,
        items,
        2024,
        "10",
        "100",
        bs_period_start=date(2024, 5, 1),
    )
    result = calculator.execute(CalculateInventoryRequest(company.id, AS_OF))
    snapshot = result.snapshots[0]
    assert snapshot.period_start == date(2024, 4, 1)
    assert snapshot.closing_inventory == Decimal("10")
    assert snapshot.cogs is None
    assert any(
        "period starts differ" in reason for reason in snapshot.unavailable_reasons
    )


def test_bs_only_fiscal_years_fall_back_to_bs_period_start(session: Session) -> None:
    calculator, _, company, source, items = _setup(session, years=())
    _insert_bs_only(
        session,
        company.id,
        source.id,
        items["INVENTORIES"],
        2023,
        date(2023, 4, 1),
        date(2024, 3, 31),
        "100",
    )
    _insert_bs_only(
        session,
        company.id,
        source.id,
        items["INVENTORIES"],
        2024,
        date(2024, 4, 1),
        date(2025, 3, 31),
        "120",
    )
    result = calculator.execute(CalculateInventoryRequest(company.id, AS_OF))
    assert result.snapshots[1].period_start == date(2024, 4, 1)
    assert result.snapshots[1].opening_inventory == Decimal("100")
    assert result.snapshots[1].inventory_change == Decimal("20")


def test_bs_only_overlapping_periods_preserve_level_but_reject_comparison(
    session: Session,
) -> None:
    calculator, _, company, source, items = _setup(session, years=())
    _insert_bs_only(
        session,
        company.id,
        source.id,
        items["INVENTORIES"],
        2023,
        date(2023, 4, 1),
        date(2024, 3, 31),
        "100",
    )
    _insert_bs_only(
        session,
        company.id,
        source.id,
        items["INVENTORIES"],
        2024,
        date(2024, 1, 1),
        date(2024, 12, 31),
        "120",
    )
    result = calculator.execute(CalculateInventoryRequest(company.id, AS_OF))
    snapshot = result.snapshots[1]
    assert snapshot.period_start == date(2024, 1, 1)
    assert snapshot.closing_inventory == Decimal("120")
    assert snapshot.opening_inventory is None
    assert snapshot.inventory_change is None
    assert any("overlaps" in reason for reason in snapshot.unavailable_reasons)


def test_append_only_recalculation_and_caller_rollback(session: Session) -> None:
    calculator, repository, company, _, _ = _setup(session, years=(2024, 2025))
    first = calculator.execute(CalculateInventoryRequest(company.id, AS_OF))
    session.commit()
    second = calculator.execute(CalculateInventoryRequest(company.id, AS_OF))
    assert len(repository.list_by_company(company.id)) == 4
    assert first.snapshots[0].id != second.snapshots[0].id
    assert first.snapshots[0].closing_inventory == second.snapshots[0].closing_inventory
    session.rollback()
    assert len(repository.list_by_company(company.id)) == 2
