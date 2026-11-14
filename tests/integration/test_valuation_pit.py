from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from cyclescope.application.dto.valuation import (
    ValuationDateQuery,
    ValuationInputRequest,
    ValuationRangeQuery,
    ValuationSnapshotQuery,
)
from cyclescope.application.use_cases.financial_data import GetFinancialStatements
from cyclescope.application.use_cases.market_data_access import MarketDataAccess
from cyclescope.application.use_cases.valuation import (
    CalculateValuationMetrics,
    GetHistoricalValuationMetrics,
    GetValuationMetricsForDate,
    GetValuationSnapshotProvenance,
    GetValuationSnapshotsAsOf,
)
from cyclescope.application.use_cases.valuation_inputs import BuildValuationInputs
from cyclescope.domain.entities.financial_data import FinancialItem
from cyclescope.domain.entities.valuation import ValuationMetricCode
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.services.valuation import default_metric_definitions
from cyclescope.domain.value_objects.financial_data import StatementType, UnitDimension
from cyclescope.infrastructure.database.models import (
    CompanyModel,
    DailyPriceModel,
    DataSourceModel,
    FinancialStatementItemModel,
    FinancialStatementModel,
    SecurityModel,
)
from cyclescope.infrastructure.database.repositories.financial_data import (
    SQLAlchemyFinancialItemRepository,
    SQLAlchemyFinancialStatementItemRepository,
    SQLAlchemyFinancialStatementRepository,
)
from cyclescope.infrastructure.database.repositories.market_data import (
    SQLAlchemyDailyPriceRepository,
    SQLAlchemyFxRateRepository,
)
from cyclescope.infrastructure.database.repositories.master_data import (
    SecuritySqlAlchemyRepository,
)
from cyclescope.infrastructure.database.repositories.valuation import (
    SQLAlchemyValuationMetricRepository,
    SQLAlchemyValuationMetricValueRepository,
)

AS_OF = datetime(2026, 5, 15, 16, tzinfo=UTC)
VALUATION_DATE = date(2026, 5, 15)


def test_historical_valuation_uses_only_revisions_visible_at_cutoff(session):
    company = CompanyModel(name="PIT Valuation Co", country_code="US")
    session.add(company)
    session.flush()
    security = SecurityModel(company_id=company.id, security_type="COMMON")
    source = DataSourceModel(code="PIT", name="PIT source", provider_type="test")
    other_source = DataSourceModel(
        code="PIT2", name="Secondary PIT source", provider_type="test"
    )
    session.add_all([security, source, other_source])
    session.flush()
    item = SQLAlchemyFinancialItemRepository(session).create(
        FinancialItem(
            "EPS",
            "Earnings per share",
            StatementType.PL,
            "income",
            UnitDimension.PER_SHARE,
        )
    )

    def add_statement(
        revision: int,
        eps: str,
        available_at: datetime,
        statement_source: DataSourceModel = source,
    ):
        statement = FinancialStatementModel(
            company_id=company.id,
            source_id=statement_source.id,
            statement_type="PL",
            accounting_standard="IFRS",
            consolidation_scope="CONSOLIDATED",
            fiscal_year=2025,
            fiscal_period="FY",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            publication_date=date(2026, 2, 1),
            publication_datetime=None,
            available_at=available_at,
            collected_at=AS_OF - timedelta(days=1),
            revision_number=revision,
            reporting_currency="USD",
        )
        session.add(statement)
        session.flush()
        session.add(
            FinancialStatementItemModel(
                financial_statement_id=statement.id,
                financial_item_id=item.id,
                value=Decimal(eps),
                currency_code="USD",
                unit_code="PER_SHARE",
                scale_multiplier=1,
            )
        )
        return statement

    statement_v1 = add_statement(1, "10", AS_OF - timedelta(days=100))
    add_statement(1, "50", AS_OF - timedelta(days=90), statement_source=other_source)

    def add_price(
        revision: int,
        close: str,
        available_at: datetime,
        price_source: DataSourceModel = source,
    ):
        price = DailyPriceModel(
            security_id=security.id,
            observation_date=VALUATION_DATE,
            open=Decimal(close),
            high=Decimal(close),
            low=Decimal(close),
            close=Decimal(close),
            adjusted_close=None,
            volume=1000,
            currency="USD",
            source_id=price_source.id,
            publication_date=None,
            available_at=available_at,
            collected_at=AS_OF - timedelta(days=1),
            revision_number=revision,
        )
        session.add(price)
        session.flush()
        return price

    price_v1 = add_price(1, "100", AS_OF - timedelta(hours=1))
    add_price(1, "200", AS_OF - timedelta(hours=2), price_source=other_source)
    financial_repository = SQLAlchemyFinancialStatementRepository(session)
    financial_lines = SQLAlchemyFinancialStatementItemRepository(session)
    market_prices = SQLAlchemyDailyPriceRepository(session)
    market = MarketDataAccess(market_prices, SQLAlchemyFxRateRepository(session))
    inputs_builder = BuildValuationInputs(
        SecuritySqlAlchemyRepository(session),
        SQLAlchemyFinancialItemRepository(session),
        GetFinancialStatements(financial_repository, financial_lines),
        market,
    )
    request = ValuationInputRequest(
        security_id=security.id,
        valuation_date=VALUATION_DATE,
        as_of=AS_OF,
        financial_source_id=source.id,
        market_source_id=source.id,
    )
    inputs_v1 = inputs_builder.execute(request)
    assert inputs_v1.reported_eps == Decimal("10")
    assert inputs_v1.closing_price == Decimal("100")
    assert inputs_v1.financial_statement_ids == (statement_v1.id,)
    assert inputs_v1.price_observation_id == price_v1.id
    deterministic_market_source = inputs_builder.execute(
        ValuationInputRequest(
            security_id=security.id,
            valuation_date=VALUATION_DATE,
            as_of=AS_OF,
            financial_source_id=source.id,
        )
    )
    assert deterministic_market_source.price_source_id == source.id
    with pytest.raises(DomainValidationError, match="financial_source_id is required"):
        inputs_builder.execute(
            ValuationInputRequest(
                security_id=security.id,
                valuation_date=VALUATION_DATE,
                as_of=AS_OF,
            )
        )

    metric_definitions = SQLAlchemyValuationMetricRepository(session)
    per_definition = next(
        row
        for row in default_metric_definitions()
        if row.metric_code == ValuationMetricCode.PER
    )
    metric_definitions.create(per_definition)
    result_repository = SQLAlchemyValuationMetricValueRepository(session)
    calculator = CalculateValuationMetrics(metric_definitions, result_repository)
    snapshot_v1 = calculator.execute(inputs_v1, (ValuationMetricCode.PER,))[0]
    assert snapshot_v1.value == Decimal("10")
    assert snapshot_v1.input_references
    assert snapshot_v1.eps_calculation_method == "REPORTED"
    assert snapshot_v1.created_at is not None

    statement_v2 = add_statement(2, "20", AS_OF + timedelta(days=1))
    price_v2 = add_price(2, "300", AS_OF + timedelta(days=1))
    inputs_after_later_revisions = inputs_builder.execute(request)
    snapshot_v2 = calculator.execute(
        inputs_after_later_revisions, (ValuationMetricCode.PER,)
    )[0]
    assert snapshot_v2.value == snapshot_v1.value
    assert snapshot_v2.id != snapshot_v1.id
    assert snapshot_v2.financial_statement_ids == (statement_v1.id,)
    assert snapshot_v2.price_observation_id == price_v1.id
    assert statement_v2.id not in snapshot_v2.financial_statement_ids
    assert price_v2.id != snapshot_v2.price_observation_id

    provenance = GetValuationSnapshotProvenance(result_repository).execute(
        snapshot_v2.id or 0
    )
    assert provenance is not None
    assert {reference.revision_number for reference in provenance.input_references} == {
        1
    }
    assert any(
        reference.parent_record_id == statement_v1.id
        for reference in provenance.input_references
    )
    on_date = GetValuationMetricsForDate(result_repository).execute(
        ValuationDateQuery(security.id, VALUATION_DATE, AS_OF)
    )
    assert len(on_date.snapshots) == 2
    over_range = GetHistoricalValuationMetrics(result_repository).execute(
        ValuationRangeQuery(
            security.id,
            VALUATION_DATE - timedelta(days=1),
            VALUATION_DATE,
            AS_OF,
        )
    )
    assert len(over_range.snapshots) == 2
    snapshots = GetValuationSnapshotsAsOf(result_repository).execute(
        ValuationSnapshotQuery(security.id, AS_OF)
    )
    assert len(snapshots.snapshots) == 2

    nested = session.begin_nested()
    calculator.execute(inputs_v1, (ValuationMetricCode.PER,))
    nested.rollback()
    assert len(result_repository.list_by_security(security.id)) == 2
