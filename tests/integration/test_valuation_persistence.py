from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from cyclescope.application.dto.valuation_percentile import (
    HistoricalValuationPercentileRequest,
)
from cyclescope.application.use_cases.valuation import (
    CalculateValuationMetrics,
    GetHistoricalValuationMetric,
)
from cyclescope.application.use_cases.valuation_percentile import (
    CalculateHistoricalValuationPercentile,
)
from cyclescope.domain.entities.valuation import (
    ValuationInputs,
    ValuationMetricCode,
    ValuationMetricValue,
    ValuationResultStatus,
    ValuationUnit,
)
from cyclescope.domain.entities.valuation_percentile import (
    HistoricalValuationObservation,
    PercentileConfidence,
    PercentileMethod,
    PercentileMetric,
    PercentileObservationAudit,
    PercentilePolicy,
    ValuationLookbackPeriod,
    ValuationPercentileResult,
    ValuationPercentileStatus,
)
from cyclescope.domain.services.valuation import default_metric_definitions
from cyclescope.domain.services.valuation_percentile import (
    calculate_valuation_percentile,
)
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

    duplicate = values.create(
        replace(
            restored,
            id=None,
            value=Decimal("16"),
            currency="JPY",
            financial_period="TTM",
            input_snapshot=(("closing_price", Decimal("1600")),),
        )
    )

    def percentile_observation(value):
        return HistoricalValuationObservation(
            observation_date=value.observation_date,
            as_of=value.as_of,
            status=value.status.value,
            value=value.value,
            currency=value.currency,
            unit=value.unit.value,
            financial_period=value.financial_period,
            calculation_version=value.calculation_version,
            market_source_id=value.price_source_id,
            financial_source_ids=value.financial_source_ids,
            snapshot_id=value.id,
            references=value.input_references,
            unavailable_reason=value.unavailable_reason,
        )

    first_observation = percentile_observation(
        replace(restored, currency="JPY", financial_period="TTM")
    )
    latest_observation = percentile_observation(duplicate)
    assert first_observation.currency == latest_observation.currency == "JPY"
    duplicate_result = calculate_valuation_percentile(
        security_id=security.id,
        company_id=company.id,
        metric=PercentileMetric.PER,
        lookback_period=ValuationLookbackPeriod.THREE_YEARS,
        as_of=NOW,
        current=latest_observation,
        observations=(first_observation, latest_observation),
        expected_sessions=(date(2026, 5, 15),),
        currency="JPY",
        unit="RATIO",
        financial_period="TTM",
        calculation_version=1,
        policy=PercentilePolicy(1, 2, 3, Decimal("0.5")),
    )
    duplicate_saved = percentile_repository.create(duplicate_result)
    audited = percentile_repository.get_by_id(duplicate_saved.id or 0)
    assert audited is not None
    assert audited.excluded_observations == 1, [
        (row.snapshot_id, row.included, row.reason, row.observation_date)
        for row in audited.observations
    ]
    audit_by_id = {row.snapshot_id: row for row in audited.observations}
    assert set(audit_by_id) == {restored.id, duplicate.id}
    assert audit_by_id[restored.id].reason == "Superseded by a later eligible snapshot."
    assert audit_by_id[duplicate.id].included


def test_database_use_case_excludes_mixed_financial_sources_with_audit(session):
    company = CompanyModel(name="Source Selection Co", country_code="US")
    session.add(company)
    session.flush()
    security = SecurityModel(company_id=company.id, security_type="COMMON")
    source = DataSourceModel(code="SRC1", name="Source one", provider_type="test")
    extra = DataSourceModel(code="SRC2", name="Source two", provider_type="test")
    session.add_all([security, source, extra])
    session.flush()

    metric_repository = SQLAlchemyValuationMetricRepository(session)
    for definition in default_metric_definitions():
        metric_repository.create(definition)
    values = SQLAlchemyValuationMetricValueRepository(session)
    selected_day = date(2026, 5, 13)
    mixed_day = date(2026, 5, 14)
    selected_as_of = datetime(2026, 5, 13, 16, tzinfo=UTC)
    mixed_as_of = datetime(2026, 5, 14, 16, tzinfo=UTC)

    def make_value(day, as_of, financial_sources, amount):
        return values.create(
            ValuationMetricValue(
                security_id=security.id,
                metric_code=ValuationMetricCode.PER,
                observation_date=day,
                as_of=as_of,
                status=ValuationResultStatus.AVAILABLE,
                value=Decimal(amount),
                currency="USD",
                unit=ValuationUnit.RATIO,
                financial_period="TTM",
                eps_calculation_method=None,
                calculation_version=1,
                price_observation_id=None,
                price_source_id=source.id,
                price_revision_number=1,
                price_available_at=as_of,
                financial_statement_ids=(),
                financial_source_ids=financial_sources,
                financial_statement_available_ats=(),
            )
        )

    selected = make_value(selected_day, selected_as_of, (source.id,), "10")
    mixed = make_value(mixed_day, mixed_as_of, (source.id, extra.id), "12")

    class _Security:
        def get_by_id(self, security_id):
            return SimpleNamespace(id=security_id, company_id=company.id)

    class _Listings:
        def list_by_security(self, security_id):
            return []

    class _Normalized:
        def list_by_company(
            self, company_id, *, metric=None, as_of=None, start_date=None
        ):
            return []

    class _Calendar:
        def expected_sessions(self, calendar_id, start_date, end_date):
            return (selected_day, mixed_day)

    class _Unused:
        def execute(self, request):
            raise AssertionError("PER does not rebuild normalized earnings.")

    percentile_repository = SQLAlchemyValuationPercentileRepository(session)
    calculation = CalculateHistoricalValuationPercentile(
        _Security(),
        _Listings(),
        values,
        _Normalized(),
        percentile_repository,
        _Calendar(),
        _Unused(),
        _Unused(),
    )
    response = calculation.execute(
        HistoricalValuationPercentileRequest(
            security_id=security.id,
            metric=PercentileMetric.PER,
            lookback_period=ValuationLookbackPeriod.THREE_YEARS,
            as_of=NOW,
            calendar_id="TEST",
            financial_source_id=source.id,
            policy=PercentilePolicy(1, 2, 3, Decimal("0.5")),
        )
    )
    saved = percentile_repository.get_by_id(response.result.id or 0)
    assert saved is not None
    audit = {row.snapshot_id: row for row in saved.observations}
    assert audit[selected.id].included
    assert not audit[mixed.id].included
    assert "unselected financial sources" in (audit[mixed.id].reason or "")
    assert saved.valid_observations == 1
    assert saved.excluded_observations == 1
