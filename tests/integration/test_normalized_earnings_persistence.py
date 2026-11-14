from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from cyclescope.application.dto.normalized_earnings import NormalizedEarningsRequest
from cyclescope.application.use_cases.financial_data import GetFinancialStatements
from cyclescope.application.use_cases.normalized_earnings import (
    CalculateNormalizedEarnings,
)
from cyclescope.domain.entities.financial_data import FinancialItem
from cyclescope.domain.entities.normalized_earnings import (
    DepreciationAmortizationSignConvention,
    EarningsMetric,
    NormalizationMethod,
)
from cyclescope.domain.entities.valuation import (
    ValuationInputReference,
    ValuationInputs,
)
from cyclescope.domain.entities.valuation_percentile import (
    PercentileConfidence,
    PercentileMethod,
    PercentileMetric,
    PercentileObservationAudit,
    ValuationLookbackPeriod,
    ValuationPercentileResult,
    ValuationPercentileStatus,
)
from cyclescope.domain.exceptions import DomainValidationError
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
from cyclescope.infrastructure.database.repositories.normalized_earnings import (
    SQLAlchemyNormalizedEarningsRepository,
)
from cyclescope.infrastructure.database.repositories.valuation_percentile import (
    SQLAlchemyValuationPercentileRepository,
)

AS_OF = datetime(2026, 6, 1, 12, tzinfo=UTC)


def test_normalized_earnings_are_pit_auditable_and_append_only(session):
    company = CompanyModel(name="Normalized Earnings Co", country_code="US")
    session.add(company)
    session.flush()
    security = SecurityModel(company_id=company.id, security_type="COMMON")
    source = DataSourceModel(
        code="NORM", name="Normalized source", provider_type="test"
    )
    secondary = DataSourceModel(
        code="NORM2", name="Secondary normalized", provider_type="test"
    )
    session.add_all([security, source, secondary])
    session.flush()

    items = SQLAlchemyFinancialItemRepository(session)
    definitions = {
        "NET_INCOME": items.create(
            FinancialItem(
                "NET_INCOME",
                "Net income",
                StatementType.PL,
                "income",
                UnitDimension.CURRENCY_AMOUNT,
            )
        ),
        "EPS": items.create(
            FinancialItem(
                "EPS", "EPS", StatementType.PL, "income", UnitDimension.PER_SHARE
            )
        ),
        "OPERATING_PROFIT": items.create(
            FinancialItem(
                "OPERATING_PROFIT",
                "Operating profit",
                StatementType.PL,
                "income",
                UnitDimension.CURRENCY_AMOUNT,
            )
        ),
        "DEPRECIATION_AMORTIZATION": items.create(
            FinancialItem(
                "DEPRECIATION_AMORTIZATION",
                "D&A",
                StatementType.PL,
                "income",
                UnitDimension.CURRENCY_AMOUNT,
            )
        ),
        "TOTAL_EQUITY": items.create(
            FinancialItem(
                "TOTAL_EQUITY",
                "Total equity",
                StatementType.BS,
                "balance",
                UnitDimension.CURRENCY_AMOUNT,
            )
        ),
        "CASH_AND_CASH_EQUIVALENTS": items.create(
            FinancialItem(
                "CASH_AND_CASH_EQUIVALENTS",
                "Cash",
                StatementType.BS,
                "balance",
                UnitDimension.CURRENCY_AMOUNT,
            )
        ),
        "SHORT_TERM_DEBT": items.create(
            FinancialItem(
                "SHORT_TERM_DEBT",
                "Short debt",
                StatementType.BS,
                "balance",
                UnitDimension.CURRENCY_AMOUNT,
            )
        ),
        "LONG_TERM_DEBT": items.create(
            FinancialItem(
                "LONG_TERM_DEBT",
                "Long debt",
                StatementType.BS,
                "balance",
                UnitDimension.CURRENCY_AMOUNT,
            )
        ),
        "SHARES_OUTSTANDING": items.create(
            FinancialItem(
                "SHARES_OUTSTANDING",
                "Shares",
                StatementType.BS,
                "balance",
                UnitDimension.SHARES,
            )
        ),
    }

    def add_statement(
        year,
        statement_source,
        lines,
        *,
        revision=1,
        available_at=None,
        statement_type="PL",
    ):
        period_end = date(year, 12, 31)
        statement = FinancialStatementModel(
            company_id=company.id,
            source_id=statement_source.id,
            statement_type=statement_type,
            accounting_standard="IFRS",
            consolidation_scope="CONSOLIDATED",
            fiscal_year=year,
            fiscal_period="FY",
            period_start=date(year, 1, 1),
            period_end=period_end,
            publication_date=period_end + timedelta(days=30),
            publication_datetime=None,
            available_at=available_at or AS_OF - timedelta(days=10),
            collected_at=AS_OF - timedelta(days=1),
            revision_number=revision,
            reporting_currency="USD",
        )
        session.add(statement)
        session.flush()
        stored_lines = {}
        for code, value in lines.items():
            unit = (
                "SHARES"
                if code == "SHARES_OUTSTANDING"
                else "PER_SHARE"
                if code == "EPS"
                else "CURRENCY"
            )
            line = FinancialStatementItemModel(
                financial_statement_id=statement.id,
                financial_item_id=definitions[code].id,
                value=Decimal(value),
                currency_code=None if unit == "SHARES" else "USD",
                unit_code=unit,
                scale_multiplier=1,
            )
            session.add(line)
            stored_lines[code] = line
        session.flush()
        return statement, stored_lines

    annual_values = {
        2021: ("10", "1", "20", "5"),
        2022: ("-5", "-1", "10", "5"),
        2023: ("0", "0", "0", "5"),
        2024: ("20", "2", "30", "5"),
        2025: ("30", "3", "40", "5"),
    }
    statements = {}
    for year, (net_income, eps, op, da) in annual_values.items():
        lines = {
            "NET_INCOME": net_income,
            "OPERATING_PROFIT": op,
            "DEPRECIATION_AMORTIZATION": da,
        }
        if year != 2025:
            lines["EPS"] = eps
        statements[year] = add_statement(
            year,
            source,
            lines,
        )
    add_statement(
        2024,
        source,
        {
            "NET_INCOME": "999",
            "EPS": "99",
            "OPERATING_PROFIT": "999",
            "DEPRECIATION_AMORTIZATION": "5",
        },
        revision=2,
        available_at=AS_OF + timedelta(days=1),
    )
    add_statement(
        2025,
        secondary,
        {
            "NET_INCOME": "500",
            "EPS": "50",
            "OPERATING_PROFIT": "500",
            "DEPRECIATION_AMORTIZATION": "5",
        },
    )
    balance, balance_lines = add_statement(
        2025,
        source,
        {
            "TOTAL_EQUITY": "500",
            "CASH_AND_CASH_EQUIVALENTS": "10",
            "SHORT_TERM_DEBT": "5",
            "LONG_TERM_DEBT": "15",
            "SHARES_OUTSTANDING": "10",
        },
        statement_type="BS",
    )
    price = DailyPriceModel(
        security_id=security.id,
        observation_date=AS_OF.date(),
        open=Decimal("100"),
        high=Decimal("100"),
        low=Decimal("100"),
        close=Decimal("100"),
        adjusted_close=None,
        volume=100,
        currency="USD",
        source_id=source.id,
        publication_date=None,
        available_at=AS_OF - timedelta(hours=1),
        collected_at=AS_OF - timedelta(hours=1),
        revision_number=1,
    )
    session.add(price)
    session.flush()

    valuation_refs = [
        ValuationInputReference(
            "DAILY_PRICE",
            price.id,
            source.id,
            1,
            price.available_at,
            observation_date=price.observation_date,
        )
    ]
    for code, line in balance_lines.items():
        valuation_refs.append(
            ValuationInputReference(
                "FINANCIAL_LINE",
                line.id,
                source.id,
                1,
                balance.available_at,
                parent_record_id=balance.id,
                financial_item_code=code,
                financial_period="FY",
                period_end=balance.period_end,
            )
        )
    valuation_inputs = ValuationInputs(
        security_id=security.id,
        observation_date=AS_OF.date(),
        as_of=AS_OF,
        currency="USD",
        closing_price=Decimal("100"),
        net_income=Decimal("30"),
        reported_eps=Decimal("3"),
        total_equity=Decimal("500"),
        cash_and_equivalents=Decimal("10"),
        short_term_debt=Decimal("5"),
        long_term_debt=Decimal("15"),
        operating_profit=Decimal("40"),
        depreciation_amortization=Decimal("5"),
        shares_outstanding=Decimal("10"),
        price_source_id=source.id,
        price_revision_number=1,
        price_observation_id=price.id,
        price_available_at=price.available_at,
        input_references=tuple(valuation_refs),
    )
    result_repo = SQLAlchemyNormalizedEarningsRepository(session)
    calculator = CalculateNormalizedEarnings(
        GetFinancialStatements(
            SQLAlchemyFinancialStatementRepository(session),
            SQLAlchemyFinancialStatementItemRepository(session),
        ),
        items,
        result_repo,
    )
    request = NormalizedEarningsRequest(
        company_id=company.id,
        security_id=security.id,
        as_of=AS_OF,
        window_years=5,
        method=NormalizationMethod.ARITHMETIC_MEAN,
        da_sign_convention=DepreciationAmortizationSignConvention.POSITIVE_EXPENSE,
        source_id=source.id,
        valuation_inputs=valuation_inputs,
    )
    calculated = calculator.execute(request)
    by_metric = {row.metric: row for row in calculated}
    assert by_metric[EarningsMetric.NET_INCOME].normalized_value == Decimal("11")
    assert by_metric[EarningsMetric.NET_INCOME].loss_making_years == 1
    assert by_metric[EarningsMetric.NET_INCOME].data_coverage == Decimal("1")
    assert by_metric[EarningsMetric.EPS].normalized_valuation_value == Decimal("200")
    assert (
        by_metric[EarningsMetric.EPS].normalized_valuation_status.value == "AVAILABLE"
    )
    assert by_metric[EarningsMetric.EBITDA].normalized_value == Decimal("25")
    assert by_metric[EarningsMetric.EBITDA].normalized_valuation_value == Decimal(
        "40.4"
    )
    assert (
        by_metric[EarningsMetric.EBITDA].normalized_valuation_status.value
        == "AVAILABLE"
    )
    assert by_metric[EarningsMetric.EPS].input_references[3].revision_number == 1
    assert (
        by_metric[EarningsMetric.EPS].input_references[3].statement_id
        == statements[2024][0].id
    )
    assert by_metric[EarningsMetric.EPS].data_coverage == Decimal("0.8")
    assert by_metric[EarningsMetric.EPS].window_end_fiscal_year == 2025
    assert all(
        ref.fiscal_year != 2025
        for ref in by_metric[EarningsMetric.EPS].input_references
    )
    assert by_metric[EarningsMetric.EPS].currency == "USD"
    assert by_metric[EarningsMetric.EPS].unit == UnitDimension.PER_SHARE
    assert len(by_metric[EarningsMetric.EPS].valuation_input_references) == 5
    assert len(by_metric[EarningsMetric.EBITDA].valuation_input_references) == 15

    persisted = result_repo.get_by_id(by_metric[EarningsMetric.EPS].id or 0)
    assert persisted is not None
    assert persisted.input_references == by_metric[EarningsMetric.EPS].input_references
    assert persisted.currency == "USD"
    assert persisted.unit == UnitDimension.PER_SHARE
    assert persisted.window_start_fiscal_year == 2021
    assert persisted.window_end_fiscal_year == 2025
    assert (
        persisted.da_sign_convention
        == DepreciationAmortizationSignConvention.POSITIVE_EXPENSE
    )
    percentile_repository = SQLAlchemyValuationPercentileRepository(session)
    normalized_eps = by_metric[EarningsMetric.EPS]
    normalized_percentile = percentile_repository.create(
        ValuationPercentileResult(
            security_id=security.id,
            company_id=company.id,
            metric=PercentileMetric.NORMALIZED_PER,
            lookback_period=ValuationLookbackPeriod.THREE_YEARS,
            method=PercentileMethod.ECDF,
            as_of=AS_OF,
            observation_start=AS_OF.date(),
            observation_end=AS_OF.date(),
            current_value=normalized_eps.normalized_valuation_value,
            percentile=None,
            historical_minimum=None,
            historical_maximum=None,
            historical_median=None,
            valid_observations=1,
            excluded_observations=0,
            expected_observations=1,
            coverage_ratio=Decimal("1"),
            status=ValuationPercentileStatus.INSUFFICIENT_DATA,
            confidence=PercentileConfidence.LOW,
            data_quality="CLEAN",
            currency="USD",
            unit="RATIO",
            financial_period="NORMALIZED:ARITHMETIC_MEAN:5:5",
            calculation_version=1,
            status_reason="At least 20 valid daily observations are required.",
            observations=(
                PercentileObservationAudit(
                    observation_date=AS_OF.date(),
                    value=normalized_eps.normalized_valuation_value,
                    included=True,
                    reason=None,
                    snapshot_id=None,
                    normalized_earnings_result_id=normalized_eps.id,
                    market_source_id=source.id,
                    financial_source_ids=(source.id,),
                    references=normalized_eps.valuation_input_references,
                ),
            ),
        )
    )
    restored_percentile = percentile_repository.get_by_id(normalized_percentile.id or 0)
    assert restored_percentile is not None
    assert (
        restored_percentile.observations[0].references
        == normalized_eps.valuation_input_references
    )
    assert len(result_repo.list_by_company(company.id, metric=EarningsMetric.EPS)) == 1
    again = calculator.execute(request)
    assert again[0].id != calculated[0].id
    assert len(result_repo.list_by_company(company.id, metric=EarningsMetric.EPS)) == 2

    nested = session.begin_nested()
    calculator.execute(request)
    nested.rollback()
    assert len(result_repo.list_by_company(company.id, metric=EarningsMetric.EPS)) == 2
    with pytest.raises(DomainValidationError, match="source_id is required"):
        calculator.execute(
            NormalizedEarningsRequest(
                company_id=company.id,
                as_of=AS_OF,
                window_years=5,
                method=NormalizationMethod.ARITHMETIC_MEAN,
            )
        )

    transaction = session.begin_nested()
    pending = calculator.execute(request)
    pending_eps = next(row for row in pending if row.metric == EarningsMetric.EPS)
    percentile_repository.create(
        replace(
            normalized_percentile,
            as_of=AS_OF + timedelta(days=1),
            observations=(
                replace(
                    normalized_percentile.observations[0],
                    normalized_earnings_result_id=pending_eps.id,
                ),
            ),
        )
    )
    transaction.rollback()
    assert len(result_repo.list_by_company(company.id, metric=EarningsMetric.EPS)) == 2
    assert len(percentile_repository.list_by_security(security.id)) == 1
