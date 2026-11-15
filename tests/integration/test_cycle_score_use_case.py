"""SQLite integration tests for Cycle Score orchestration and persistence."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from cyclescope.application.dto.cycle_score import CalculateCycleScoreRequest
from cyclescope.application.use_cases.cycle_score import CalculateCycleScore
from cyclescope.application.use_cases.financial_data import GetFinancialStatements
from cyclescope.application.use_cases.normalized_earnings import (
    CalculateNormalizedEarnings,
)
from cyclescope.domain.entities.cycle_score import (
    CyclePhase,
    CycleScoreConfig,
    CycleScoreStatus,
)
from cyclescope.domain.entities.financial_data import FinancialItem
from cyclescope.domain.entities.normalized_earnings import (
    EarningsMetric,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.financial_data import StatementType, UnitDimension
from cyclescope.infrastructure.database.models import (
    CompanyModel,
    DataSourceModel,
    FinancialStatementItemModel,
    FinancialStatementModel,
    SecurityModel,
)
from cyclescope.infrastructure.database.models.cycle_score import CycleScoreModel
from cyclescope.infrastructure.database.models.normalized_earnings import (
    NormalizedEarningsResultModel,
)
from cyclescope.infrastructure.database.repositories.cycle_score import (
    SQLAlchemyCycleScoreRepository,
)
from cyclescope.infrastructure.database.repositories.financial_data import (
    SQLAlchemyFinancialItemRepository,
    SQLAlchemyFinancialStatementItemRepository,
    SQLAlchemyFinancialStatementRepository,
)
from cyclescope.infrastructure.database.repositories.master_data import (
    SecuritySqlAlchemyRepository,
)
from cyclescope.infrastructure.database.repositories.normalized_earnings import (
    SQLAlchemyNormalizedEarningsRepository,
)

AS_OF = datetime(2026, 6, 1, 12, tzinfo=UTC)


def _setup(session, values=None, *, missing_years=()):
    company = CompanyModel(name="Cycle Issuer", country_code="US")
    session.add(company)
    session.flush()
    security = SecurityModel(company_id=company.id, security_type="COMMON")
    source = DataSourceModel(
        code="CYCLE_PRIMARY", name="Cycle primary", provider_type="test"
    )
    session.add_all([security, source])
    session.flush()
    item = SQLAlchemyFinancialItemRepository(session).create(
        FinancialItem(
            "OPERATING_PROFIT",
            "Operating profit",
            StatementType.PL,
            "income",
            UnitDimension.CURRENCY_AMOUNT,
        )
    )
    statement_values = values or {
        2021: "10",
        2022: "20",
        2023: "30",
        2024: "40",
        2025: "50",
    }
    statements = {}
    for year, value in statement_values.items():
        if year in missing_years:
            continue
        statement = FinancialStatementModel(
            company_id=company.id,
            source_id=source.id,
            statement_type="PL",
            accounting_standard="IFRS",
            consolidation_scope="CONSOLIDATED",
            fiscal_year=year,
            fiscal_period="FY",
            period_start=date(year, 1, 1),
            period_end=date(year, 12, 31),
            publication_date=date(year + 1, 2, 1),
            publication_datetime=None,
            available_at=datetime(year + 1, 2, 1, tzinfo=UTC),
            collected_at=datetime(year + 1, 2, 2, tzinfo=UTC),
            revision_number=1,
            reporting_currency="USD",
        )
        session.add(statement)
        session.flush()
        line = FinancialStatementItemModel(
            financial_statement_id=statement.id,
            financial_item_id=item.id,
            value=Decimal(value),
            currency_code="USD",
            unit_code="CURRENCY",
            scale_multiplier=1,
        )
        session.add(line)
        session.flush()
        statements[year] = (statement, line)
    if 2025 in statements:
        q4 = FinancialStatementModel(
            company_id=company.id,
            source_id=source.id,
            statement_type="PL",
            accounting_standard="IFRS",
            consolidation_scope="CONSOLIDATED",
            fiscal_year=2025,
            fiscal_period="Q4",
            period_start=date(2025, 10, 1),
            period_end=date(2025, 12, 31),
            publication_date=date(2026, 2, 1),
            publication_datetime=None,
            available_at=datetime(2026, 2, 1, tzinfo=UTC),
            collected_at=datetime(2026, 2, 2, tzinfo=UTC),
            revision_number=1,
            reporting_currency="USD",
        )
        session.add(q4)
        session.flush()
        session.add(
            FinancialStatementItemModel(
                financial_statement_id=q4.id,
                financial_item_id=item.id,
                value=Decimal("9999"),
                currency_code="USD",
                unit_code="CURRENCY",
                scale_multiplier=1,
            )
        )
    # This revision was collected and published after the requested PIT cutoff.
    future_statement = FinancialStatementModel(
        company_id=company.id,
        source_id=source.id,
        statement_type="PL",
        accounting_standard="IFRS",
        consolidation_scope="CONSOLIDATED",
        fiscal_year=2024,
        fiscal_period="FY",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 12, 31),
        publication_date=date(2026, 7, 1),
        publication_datetime=None,
        available_at=AS_OF + timedelta(days=30),
        collected_at=AS_OF + timedelta(days=31),
        revision_number=2,
        reporting_currency="USD",
    )
    if 2024 in statements:
        session.add(future_statement)
        session.flush()
        session.add(
            FinancialStatementItemModel(
                financial_statement_id=future_statement.id,
                financial_item_id=item.id,
                value=Decimal("9999"),
                currency_code="USD",
                unit_code="CURRENCY",
                scale_multiplier=1,
            )
        )
    session.flush()
    financial_query = GetFinancialStatements(
        SQLAlchemyFinancialStatementRepository(session),
        SQLAlchemyFinancialStatementItemRepository(session),
    )
    normalized_repository = SQLAlchemyNormalizedEarningsRepository(session)
    normalizer = CalculateNormalizedEarnings(
        financial_query,
        SQLAlchemyFinancialItemRepository(session),
        normalized_repository,
    )
    cycle_repository = SQLAlchemyCycleScoreRepository(session)
    calculator = CalculateCycleScore(
        normalizer,
        cycle_repository,
        SecuritySqlAlchemyRepository(session),
    )
    return (
        calculator,
        cycle_repository,
        normalized_repository,
        company,
        security,
        source,
        statements,
    )


def _request(company_id, security_id, source_id=None, *, config=None):
    return CalculateCycleScoreRequest(
        company_id=company_id,
        security_id=security_id,
        financial_source_id=source_id,
        as_of=AS_OF,
        config=config or CycleScoreConfig(window_years=5),
    )


def test_cycle_score_uses_pit_fy_operating_profit_and_round_trips(session) -> None:
    calculator, repository, normalized, company, security, source, statements = _setup(
        session
    )
    # With a single eligible financial source, omission of source selection is
    # deterministic and the selected source is inferred from exact references.
    response = calculator.execute(_request(company.id, security.id))
    result = response.score
    assert result.id is not None
    assert result.status == CycleScoreStatus.AVAILABLE
    assert result.phase == CyclePhase.EXPANSION
    assert result.coverage == Decimal("1.0000000")
    assert result.source_id == source.id
    assert len(result.input_references) == 5
    assert {ref.fiscal_year for ref in result.input_references} == set(statements)
    assert {ref.source_id for ref in result.input_references} == {source.id}
    assert all(ref.available_at <= AS_OF for ref in result.input_references)
    assert all(ref.revision_number == 1 for ref in result.input_references)
    assert all(ref.period_start is not None for ref in result.input_references)
    assert all(ref.publication_date is not None for ref in result.input_references)
    assert all(ref.normalized_earnings_result_id > 0 for ref in result.input_references)
    assert result.config_snapshot["weights"] == {
        "EARNINGS_MOMENTUM": "0.35",
        "EARNINGS_ACCELERATION": "0.25",
        "HISTORICAL_POSITION": "0.15",
        "TREND_CONFIRMATION": "0.25",
    }
    restored = repository.get_by_id(result.id)
    assert restored == result
    assert len(repository.list_by_company(company.id, as_of=AS_OF)) == 1
    op_results = normalized.list_by_company(
        company.id, metric=EarningsMetric.OPERATING_PROFIT, as_of=AS_OF
    )
    assert len(op_results) == 1
    assert op_results[0].id == result.normalized_earnings_result_id


def test_missing_financial_history_is_explicitly_insufficient(session) -> None:
    calculator, repository, _, company, security, source, _ = _setup(
        session, values={}, missing_years=(2021, 2022, 2023, 2024, 2025)
    )
    result = calculator.execute(_request(company.id, security.id, source.id)).score
    assert result.status == CycleScoreStatus.INSUFFICIENT_DATA
    assert result.phase == CyclePhase.UNKNOWN
    assert result.score is None
    assert result.coverage is None
    assert result.input_references == ()
    assert "observations" in result.status_reason
    assert repository.get_by_id(result.id or 0) == result


def test_cycle_score_window_preserves_missing_year_coverage(session) -> None:
    values = {2020: "10", 2021: "20", 2022: "30", 2023: "40", 2024: "50", 2025: "60"}
    calculator, _, _, company, security, source, _ = _setup(
        session, values=values, missing_years=(2022,)
    )
    result = calculator.execute(
        _request(
            company.id,
            security.id,
            source.id,
            config=CycleScoreConfig(window_years=7),
        )
    ).score
    assert result.coverage == Decimal("0.8333333")
    assert 2022 not in {reference.fiscal_year for reference in result.input_references}
    assert result.status == CycleScoreStatus.AVAILABLE


def test_source_ambiguity_propagates_and_does_not_save_cycle_score(session) -> None:
    calculator, repository, _, company, security, _, statements = _setup(session)
    secondary = DataSourceModel(
        code="CYCLE_SECONDARY2", name="Second source", provider_type="test"
    )
    session.add(secondary)
    session.flush()
    item_id = statements[2021][1].financial_item_id
    statement = FinancialStatementModel(
        company_id=company.id,
        source_id=secondary.id,
        statement_type="PL",
        accounting_standard="IFRS",
        consolidation_scope="CONSOLIDATED",
        fiscal_year=2021,
        fiscal_period="FY",
        period_start=date(2021, 1, 1),
        period_end=date(2021, 12, 31),
        publication_date=date(2022, 2, 1),
        publication_datetime=None,
        available_at=datetime(2022, 2, 1, tzinfo=UTC),
        collected_at=datetime(2022, 2, 2, tzinfo=UTC),
        revision_number=1,
        reporting_currency="USD",
    )
    session.add(statement)
    session.flush()
    session.add(
        FinancialStatementItemModel(
            financial_statement_id=statement.id,
            financial_item_id=item_id,
            value=Decimal("12"),
            currency_code="USD",
            unit_code="CURRENCY",
            scale_multiplier=1,
        )
    )
    session.flush()
    with pytest.raises(DomainValidationError, match="source_id is required"):
        calculator.execute(
            CalculateCycleScoreRequest(
                company_id=company.id,
                security_id=security.id,
                as_of=AS_OF,
                config=CycleScoreConfig(window_years=5),
            )
        )
    assert repository.list_by_company(company.id) == []
    assert session.query(CycleScoreModel).count() == 0


def test_currency_incompatible_annual_history_is_rejected(session) -> None:
    calculator, repository, _, company, security, source, statements = _setup(session)
    statements[2021][0].reporting_currency = "JPY"
    session.flush()
    with pytest.raises(DomainValidationError, match="different standards/scopes"):
        calculator.execute(_request(company.id, security.id, source.id))
    assert repository.list_by_company(company.id) == []
    assert session.query(CycleScoreModel).count() == 0


def test_security_must_belong_to_requested_company(session) -> None:
    calculator, repository, normalized, company, _, source, _ = _setup(session)
    another_company = CompanyModel(name="Different issuer", country_code="US")
    session.add(another_company)
    session.flush()
    other_security = SecurityModel(
        company_id=another_company.id, security_type="COMMON"
    )
    session.add(other_security)
    session.flush()
    with pytest.raises(DomainValidationError, match="does not belong"):
        calculator.execute(_request(company.id, other_security.id, source.id))
    assert repository.list_by_company(company.id) == []
    assert normalized.list_by_company(company.id) == []


def test_cycle_score_and_normalized_snapshots_share_caller_rollback(session) -> None:
    calculator, repository, normalized, company, security, source, _ = _setup(session)
    first = calculator.execute(_request(company.id, security.id, source.id)).score
    session.commit()
    baseline_cycles = len(repository.list_by_company(company.id))
    baseline_normalized = len(
        normalized.list_by_company(company.id, metric=EarningsMetric.OPERATING_PROFIT)
    )
    transaction = session.begin_nested()
    second = calculator.execute(_request(company.id, security.id, source.id)).score
    assert second.id != first.id
    transaction.rollback()
    assert len(repository.list_by_company(company.id)) == baseline_cycles
    assert repository.get_by_id(first.id or 0) == first
    assert (
        len(
            normalized.list_by_company(
                company.id, metric=EarningsMetric.OPERATING_PROFIT
            )
        )
        == baseline_normalized
    )
    assert session.query(CycleScoreModel).count() == 1
    assert session.query(NormalizedEarningsResultModel).count() == 4


def test_recalculation_appends_historical_cycle_score_snapshots(session) -> None:
    calculator, repository, normalized, company, security, source, _ = _setup(session)
    first = calculator.execute(_request(company.id, security.id, source.id)).score
    second = calculator.execute(_request(company.id, security.id, source.id)).score
    assert first.id != second.id
    history = repository.list_by_company(company.id, as_of=AS_OF)
    assert [item.id for item in history] == [first.id, second.id]
    assert (
        len(
            normalized.list_by_company(
                company.id, metric=EarningsMetric.OPERATING_PROFIT
            )
        )
        == 2
    )
