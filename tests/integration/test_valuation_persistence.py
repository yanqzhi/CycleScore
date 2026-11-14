from dataclasses import replace
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
from cyclescope.domain.entities.valuation_percentile import (
    PercentileConfidence,
    PercentileMethod,
    PercentileMetric,
    PercentileObservationAudit,
    ValuationLookbackPeriod,
    ValuationPercentileResult,
    ValuationPercentileStatus,
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
from cyclescope.infrastructure.database.repositories.valuation_percentile import (
    SQLAlchemyValuationPercentileRepository,
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
    # Caller-level IDs without an EPS line reference are not persisted as
    # provenance for a reported EPS calculation.
    assert calculated[0].financial_statement_ids == ()
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

    percentile_repository = SQLAlchemyValuationPercentileRepository(session)
    percentile = ValuationPercentileResult(
        security_id=security.id,
        company_id=company.id,
        metric=PercentileMetric.PER,
        lookback_period=ValuationLookbackPeriod.THREE_YEARS,
        method=PercentileMethod.ECDF,
        as_of=NOW,
        observation_start=date(2026, 5, 15),
        observation_end=date(2026, 5, 15),
        current_value=Decimal("15"),
        percentile=Decimal("100"),
        historical_minimum=Decimal("15"),
        historical_maximum=Decimal("15"),
        historical_median=Decimal("15"),
        valid_observations=1,
        excluded_observations=0,
        expected_observations=1,
        coverage_ratio=Decimal("1"),
        status=ValuationPercentileStatus.AVAILABLE,
        confidence=PercentileConfidence.LOW,
        data_quality="CLEAN",
        currency="JPY",
        unit="RATIO",
        financial_period="TTM",
        calculation_version=1,
        status_reason=None,
        observations=(
            PercentileObservationAudit(
                observation_date=date(2026, 5, 15),
                value=Decimal("15"),
                included=True,
                reason=None,
                snapshot_id=restored.id,
                normalized_earnings_result_id=None,
                market_source_id=source.id,
                financial_source_ids=(),
                references=restored.input_references,
            ),
        ),
    )
    saved = percentile_repository.create(percentile)
    assert saved.id is not None
    assert saved.observations == percentile.observations
    assert percentile_repository.get_by_id(saved.id) == saved
    assert percentile_repository.list_by_security(security.id, as_of=NOW) == [saved]
    later = percentile_repository.create(
        replace(percentile, as_of=NOW + timedelta(days=1))
    )
    assert later.id != saved.id
    assert percentile_repository.list_by_security(security.id) == [saved, later]
    nested = session.begin_nested()
    percentile_repository.create(percentile)
    nested.rollback()
    assert percentile_repository.list_by_security(security.id) == [saved, later]
