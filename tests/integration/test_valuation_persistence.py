from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from cyclescope.application.use_cases.valuation import (
    CalculateValuationMetrics,
    GetHistoricalValuationMetric,
)
from cyclescope.domain.entities.valuation import (
    ValuationInputs,
    ValuationMetricCode,
)
from cyclescope.domain.services.valuation import default_metric_definitions
from cyclescope.infrastructure.database.models import (
    CompanyModel,
    DataSourceModel,
    SecurityModel,
)
from cyclescope.infrastructure.database.repositories.valuation import (
    SQLAlchemyValuationMetricRepository,
    SQLAlchemyValuationMetricValueRepository,
)

NOW = datetime(2026, 5, 15, 16, tzinfo=UTC)


def test_metric_definitions_seeded_calculation_and_historical_retrieval(session):
    company = CompanyModel(name="Valuation Co", country_code="JP")
    session.add(company)
    session.flush()
    security = SecurityModel(company_id=company.id, security_type="COMMON")
    session.add(security)
    session.flush()
    source = DataSourceModel(code="VALSRC", name="Valuation", provider_type="test")
    session.add(source)
    session.flush()

    metric_repo = SQLAlchemyValuationMetricRepository(session)
    for definition in default_metric_definitions():
        metric_repo.create(definition)
    values = SQLAlchemyValuationMetricValueRepository(session)
    calculate = CalculateValuationMetrics(metric_repo, values)
    calculated = calculate.execute(
        ValuationInputs(
            security_id=security.id,
            observation_date=date(2026, 5, 15),
            as_of=NOW,
            currency="JPY",
            closing_price=Decimal("1500"),
            reported_eps=Decimal("100"),
            price_source_id=source.id,
            price_revision_number=2,
            financial_statement_ids=(11,),
            financial_source_ids=(3,),
        ),
        (ValuationMetricCode.PER,),
    )
    assert calculated[0].value == Decimal("15")
    assert calculated[0].price_source_id == source.id
    assert calculated[0].financial_statement_ids == (11,)
    assert calculated[0].input_snapshot == (
        ("closing_price", Decimal("1500")),
        ("reported_eps", Decimal("100")),
    )

    query = GetHistoricalValuationMetric(values)
    assert (
        query.execute(
            security.id,
            ValuationMetricCode.PER,
            date(2026, 5, 15),
            NOW - timedelta(seconds=1),
        )
        is None
    )
    restored = query.execute(
        security.id, ValuationMetricCode.PER, date(2026, 5, 15), NOW
    )
    assert restored is not None
    assert restored.value == Decimal("15")
    assert restored.input_snapshot == calculated[0].input_snapshot
    assert values.list_by_security(security.id, ValuationMetricCode.PER) == [restored]
