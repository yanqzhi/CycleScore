from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from cyclescope.application.dto.value_score import CalculateValueScoreRequest
from cyclescope.application.use_cases.financial_data import GetFinancialStatements
from cyclescope.application.use_cases.market_data_access import MarketDataAccess
from cyclescope.application.use_cases.valuation_inputs import BuildValuationInputs
from cyclescope.application.use_cases.valuation_percentile import (
    CalculateHistoricalValuationPercentile,
)
from cyclescope.application.use_cases.value_score import CalculateValueScore
from cyclescope.domain.entities.valuation import (
    ValuationInputs,
    ValuationMetricCode,
    ValuationMetricValue,
    ValuationResultStatus,
    ValuationUnit,
)
from cyclescope.domain.entities.valuation_percentile import (
    PercentileMetric,
    ValuationLookbackPeriod,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.services.valuation import default_metric_definitions
from cyclescope.infrastructure.database.models import (
    CompanyIndustryExposureModel,
    CompanyModel,
    DataSourceModel,
    IndustryModel,
    SecurityModel,
    SubIndustryModel,
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
    CompanyIndustryExposureSqlAlchemyRepository,
    ListingSqlAlchemyRepository,
    SecuritySqlAlchemyRepository,
)
from cyclescope.infrastructure.database.repositories.normalized_earnings import (
    SQLAlchemyNormalizedEarningsRepository,
)
from cyclescope.infrastructure.database.repositories.valuation import (
    SQLAlchemyValuationMetricRepository,
    SQLAlchemyValuationMetricValueRepository,
)
from cyclescope.infrastructure.database.repositories.valuation_percentile import (
    SQLAlchemyValuationPercentileRepository,
)
from cyclescope.infrastructure.database.repositories.value_score import (
    SQLAlchemyValueScoreRepository,
)

AS_OF = datetime(2026, 1, 31, 16, tzinfo=UTC)


class _SecurityRepo:
    def get_by_id(self, security_id):
        return SimpleNamespace(id=security_id, company_id=7)


class _PriceRepo:
    def get_by_security_and_period(self, *args):
        return []


class _ExposureRepo:
    def list_by_company(self, company_id):
        return []


class _PercentileUseCase:
    def __init__(self, error=None):
        self.requests = []
        self.error = error

    def execute(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        value = (
            Decimal(25)
            if request.metric
            in {
                PercentileMetric.PER,
                PercentileMetric.NORMALIZED_PER,
            }
            else None
        )
        result = SimpleNamespace(
            id=len(self.requests),
            percentile=value,
            status_reason=None,
            as_of=request.as_of,
            observations=(),
        )
        return SimpleNamespace(result=result)


class _TradingCalendar:
    def expected_sessions(self, calendar_id, start_date, end_date):
        return (end_date,)


class _InputBuilder:
    def __init__(self, error=None):
        self.error = error

    def execute(self, request):
        if self.error:
            raise self.error
        return ValuationInputs(
            security_id=request.security_id,
            observation_date=request.valuation_date,
            as_of=request.as_of,
            currency="JPY",
        )


class _ScoreRepo:
    def __init__(self):
        self.created = None

    def create(self, result):
        self.created = result
        return result


def test_value_score_reuses_pit_services_and_persists_missingness() -> None:
    percentile = _PercentileUseCase()
    results = _ScoreRepo()
    use_case = CalculateValueScore(
        securities=_SecurityRepo(),
        prices=_PriceRepo(),
        values=object(),
        exposures=_ExposureRepo(),
        results=results,
        percentile_calculator=percentile,
        valuation_input_builder=_InputBuilder(),
    )
    response = use_case.execute(
        CalculateValueScoreRequest(
            security_id=1,
            as_of=datetime(2026, 1, 31, tzinfo=UTC),
            calendar_id="TSE",
            market_source_id=2,
            financial_source_id=4,
            lookback_period=ValuationLookbackPeriod.FIVE_YEARS,
        )
    )
    assert response.score is results.created
    assert (
        response.score.score is None
    )  # price, cash flow, and balance coverage too low
    assert response.score.components[3].reason.startswith("Operating cash flow")
    assert [request.metric for request in percentile.requests] == [
        PercentileMetric.PER,
        PercentileMetric.PBR,
        PercentileMetric.NORMALIZED_PER,
        PercentileMetric.NORMALIZED_EV_EBITDA,
    ]
    assert all(request.as_of == response.score.as_of for request in percentile.requests)
    assert all(request.market_source_id == 2 for request in percentile.requests)
    assert all(request.financial_source_id == 4 for request in percentile.requests)


def test_expected_data_unavailability_becomes_partial_component() -> None:
    results = _ScoreRepo()
    use_case = CalculateValueScore(
        securities=_SecurityRepo(),
        prices=_PriceRepo(),
        values=object(),
        exposures=_ExposureRepo(),
        results=results,
        percentile_calculator=_PercentileUseCase(),
        valuation_input_builder=_InputBuilder(),
    )
    result = use_case.execute(
        CalculateValueScoreRequest(
            security_id=1,
            as_of=datetime(2026, 1, 31, tzinfo=UTC),
            calendar_id="TSE",
        )
    ).score
    assert result.components[4].status.value == "UNAVAILABLE"
    assert results.created is result


def test_real_services_represent_missing_financial_and_market_data_as_unavailable(
    session,
) -> None:
    company = CompanyModel(name="No Data Co", country_code="JP")
    session.add(company)
    session.flush()
    security_model = SecurityModel(company_id=company.id, security_type="COMMON")
    session.add(security_model)
    session.flush()

    securities = SecuritySqlAlchemyRepository(session)
    prices = SQLAlchemyDailyPriceRepository(session)
    statements = SQLAlchemyFinancialStatementRepository(session)
    statement_items = SQLAlchemyFinancialStatementItemRepository(session)
    financial_items = SQLAlchemyFinancialItemRepository(session)
    financial_query = GetFinancialStatements(statements, statement_items)
    market_access = MarketDataAccess(prices, SQLAlchemyFxRateRepository(session))
    input_builder = BuildValuationInputs(
        securities, financial_items, financial_query, market_access
    )
    metric_values = SQLAlchemyValuationMetricValueRepository(session)
    percentile_calculator = CalculateHistoricalValuationPercentile(
        securities=securities,
        listings=ListingSqlAlchemyRepository(session),
        valuation_values=metric_values,
        normalized_earnings=SQLAlchemyNormalizedEarningsRepository(session),
        results=SQLAlchemyValuationPercentileRepository(session),
        calendar=_TradingCalendar(),
        valuation_input_builder=input_builder,
        normalized_calculator=object(),
    )
    use_case = CalculateValueScore(
        securities=securities,
        prices=prices,
        values=metric_values,
        exposures=CompanyIndustryExposureSqlAlchemyRepository(session),
        results=SQLAlchemyValueScoreRepository(session),
        percentile_calculator=percentile_calculator,
        valuation_input_builder=input_builder,
    )
    result = use_case.execute(
        CalculateValueScoreRequest(
            security_id=security_model.id,
            as_of=AS_OF,
            calendar_id="TSE",
        )
    ).score
    assert result.components[1].status.value == "UNAVAILABLE"
    assert result.components[2].status.value == "UNAVAILABLE"
    assert result.components[4].status.value == "UNAVAILABLE"
    assert result.score is None
    assert (
        len(SQLAlchemyValueScoreRepository(session).list_by_security(security_model.id))
        == 1
    )


def test_currency_mismatch_propagates_without_snapshot() -> None:
    results = _ScoreRepo()
    use_case = CalculateValueScore(
        securities=_SecurityRepo(),
        prices=_PriceRepo(),
        values=object(),
        exposures=_ExposureRepo(),
        results=results,
        percentile_calculator=_PercentileUseCase(),
        valuation_input_builder=_InputBuilder(
            DomainValidationError("currency mismatch")
        ),
    )
    try:
        use_case.execute(
            CalculateValueScoreRequest(
                security_id=1,
                as_of=datetime(2026, 1, 31, tzinfo=UTC),
                calendar_id="TSE",
            )
        )
    except DomainValidationError as error:
        assert str(error) == "currency mismatch"
    else:
        raise AssertionError("Currency mismatch was suppressed.")
    assert results.created is None


def test_source_and_pit_integrity_errors_propagate_without_snapshot() -> None:
    for message in (
        "financial_source_id is required when multiple sources are eligible.",
        "The selected financial source is invalid.",
        "Financial statement input is unavailable at as_of.",
    ):
        results = _ScoreRepo()
        use_case = CalculateValueScore(
            securities=_SecurityRepo(),
            prices=_PriceRepo(),
            values=object(),
            exposures=_ExposureRepo(),
            results=results,
            percentile_calculator=_PercentileUseCase(DomainValidationError(message)),
            valuation_input_builder=_InputBuilder(),
        )
        try:
            use_case.execute(
                CalculateValueScoreRequest(
                    security_id=1,
                    as_of=datetime(2026, 1, 31, tzinfo=UTC),
                    calendar_id="TSE",
                )
            )
        except DomainValidationError as error:
            assert str(error) == message
        else:
            raise AssertionError("Integrity error was suppressed.")
        assert results.created is None


def test_relative_valuation_uses_only_pit_source_and_period_comparable_peers(
    session,
) -> None:
    industry = IndustryModel(code="TECH", name="Technology")
    other_industry = IndustryModel(code="UTIL", name="Utilities")
    session.add_all([industry, other_industry])
    session.flush()
    technology = SubIndustryModel(
        industry_id=industry.id, code="SOFTWARE", name="Software"
    )
    utilities = SubIndustryModel(
        industry_id=other_industry.id, code="POWER", name="Power"
    )
    session.add_all([technology, utilities])
    companies = [
        CompanyModel(name=f"Issuer {index}", country_code="JP") for index in range(11)
    ]
    session.add_all(companies)
    session.flush()
    securities = [
        SecurityModel(company_id=company.id, security_type="COMMON")
        for company in companies
    ]
    session.add_all(securities)
    market_source = DataSourceModel(
        code="VALUE_MARKET", name="Value market", provider_type="test"
    )
    market_source_other = DataSourceModel(
        code="OTHER_MARKET", name="Other market", provider_type="test"
    )
    session.add_all([market_source, market_source_other])
    session.flush()
    session.add_all(
        [
            CompanyIndustryExposureModel(
                company_id=companies[index].id,
                sub_industry_id=(utilities.id if index == 10 else technology.id),
                revenue_share=Decimal("0.8"),
                valid_from=date(2020, 1, 1),
            )
            for index in range(11)
        ]
    )
    metric_repository = SQLAlchemyValuationMetricRepository(session)
    for definition in default_metric_definitions():
        metric_repository.create(definition)
    values = SQLAlchemyValuationMetricValueRepository(session)

    def save_value(
        security_id,
        metric,
        value,
        *,
        financial_source=1,
        price_source=market_source.id,
        currency="JPY",
        period="TTM",
        version=1,
        as_of=AS_OF,
    ):
        values.create(
            ValuationMetricValue(
                security_id=security_id,
                metric_code=metric,
                observation_date=AS_OF.date(),
                as_of=as_of,
                status=ValuationResultStatus.AVAILABLE,
                value=Decimal(value),
                currency=currency,
                unit=ValuationUnit.RATIO,
                financial_period=period,
                eps_calculation_method=None,
                calculation_version=version,
                price_observation_id=None,
                price_source_id=price_source,
                price_revision_number=1,
                price_available_at=AS_OF,
                financial_statement_ids=(),
                financial_source_ids=(financial_source,),
                financial_statement_available_ats=(),
            )
        )

    codes = (
        ValuationMetricCode.PER,
        ValuationMetricCode.PBR,
        ValuationMetricCode.EV_EBITDA,
    )
    peer_values = (Decimal(15), Decimal(20), Decimal(25), Decimal(30))
    for metric_index, metric in enumerate(codes):
        save_value(securities[0].id, metric, 10 + metric_index)
        for peer_index, peer_value in enumerate(peer_values, start=1):
            if not (peer_index == 4 and metric == ValuationMetricCode.PER):
                save_value(securities[peer_index].id, metric, peer_value + metric_index)
        # These eligible snapshots violate one comparability dimension each.
        save_value(
            securities[5].id,
            metric,
            999,
            financial_source=2,
        )
        save_value(
            securities[6].id,
            metric,
            999,
            price_source=market_source_other.id,
        )
        save_value(
            securities[7].id,
            metric,
            999,
            currency="USD",
        )
        save_value(
            securities[8].id,
            metric,
            999,
            period="FY",
        )
        save_value(
            securities[9].id,
            metric,
            999,
            version=2,
        )
        # A future available revision is excluded at the historical cutoff.
        save_value(
            securities[1].id,
            metric,
            999,
            as_of=datetime(2026, 2, 2, tzinfo=UTC),
        )
        # A second full source cohort is used to verify deterministic tie-breaking.
        save_value(
            securities[0].id,
            metric,
            100 + metric_index,
            financial_source=2,
            price_source=market_source_other.id,
        )
        for peer_index, peer_value in enumerate((200, 300, 400), start=1):
            save_value(
                securities[peer_index].id,
                metric,
                peer_value + metric_index,
                financial_source=2,
                price_source=market_source_other.id,
            )
    # PER has four eligible peers in source cohort 2, while PBR and EV/EBITDA
    # have only three. This verifies the documented per-metric policy.
    save_value(
        securities[4].id,
        ValuationMetricCode.PER,
        500,
        financial_source=2,
        price_source=market_source_other.id,
    )

    exposures = CompanyIndustryExposureSqlAlchemyRepository(session)
    target = securities[0]
    peers = tuple(row.id for row in securities[1:4])
    calculator = CalculateValueScore(
        securities=SecuritySqlAlchemyRepository(session),
        prices=SQLAlchemyDailyPriceRepository(session),
        values=values,
        exposures=exposures,
        results=SQLAlchemyValueScoreRepository(session),
        percentile_calculator=_PercentileUseCase(),
        valuation_input_builder=_InputBuilder(),
    )

    def run_score(peer_ids):
        return calculator.execute(
            CalculateValueScoreRequest(
                security_id=target.id,
                as_of=AS_OF,
                calendar_id="TSE",
                peer_security_ids=peer_ids,
            )
        ).score

    enough_peers = run_score(peers)
    relative = enough_peers.components[5]
    assert relative.coverage == Decimal(1)
    assert len(relative.peer_security_ids) == 3
    assert {measure.code for measure in relative.measures} == {
        "PER",
        "PBR",
        "EV_EBITDA",
    }
    assert next(m for m in relative.measures if m.code == "PER").value == Decimal("0.5")
    assert all(ref.available_at <= AS_OF for ref in relative.input_references)

    # Three source-1 peers remain eligible when an additional same-industry
    # source-2 peer is supplied without selecting either source explicitly.
    with_incompatible_extra = run_score((*peers, securities[5].id)).components[5]
    assert with_incompatible_extra.status.value == "AVAILABLE"
    assert with_incompatible_extra.peer_security_ids == peers
    assert securities[5].id in {
        peer_id for peer_id, _ in with_incompatible_extra.excluded_peer_reasons
    }
    incompatible_reason = dict(with_incompatible_extra.excluded_peer_reasons)[
        securities[5].id
    ]
    assert "source" in incompatible_reason.lower()
    assert all(code in incompatible_reason for code in ("PER", "PBR", "EV_EBITDA"))
    assert next(
        measure for measure in with_incompatible_extra.measures if measure.code == "PER"
    ).value == Decimal("0.5")

    insufficient = run_score((securities[1].id, securities[2].id, securities[5].id))
    assert insufficient.components[5].status.value == "UNAVAILABLE"
    assert not insufficient.components[5].peer_security_ids
    assert all(
        "source cohort" in reason
        for _, reason in insufficient.components[5].excluded_peer_reasons
    )

    deterministic_score = run_score(peers)
    deterministic = deterministic_score.components[5]
    repeated = run_score(peers).components[5]
    assert next(m for m in deterministic.measures if m.code == "PER").value == Decimal(
        "0.5"
    )
    assert repeated.score == deterministic.score
    assert repeated.peer_security_ids == deterministic.peer_security_ids
    assert repeated.input_references == deterministic.input_references
    assert {
        reference.financial_source_ids for reference in deterministic.input_references
    } == {(1,)}
    assert {reference.source_id for reference in deterministic.input_references} == {
        market_source.id
    }
    for code in ("PER", "PBR", "EV_EBITDA"):
        metric_references = [
            reference
            for reference in deterministic.input_references
            if reference.reference_code == code
        ]
        assert {reference.security_id for reference in metric_references} == {
            target.id,
            *peers,
        }
        assert {reference.financial_source_ids for reference in metric_references} == {
            (1,)
        }
        assert {reference.source_id for reference in metric_references} == {
            market_source.id
        }

    # Cohorts are selected independently for each metric and remain explicit in
    # the metric-coded references: source 2 wins PER, source 1 wins PBR and EV.
    per_metric = run_score((*peers, securities[4].id)).components[5]
    by_metric = {
        code: [ref for ref in per_metric.input_references if ref.reference_code == code]
        for code in ("PER", "PBR", "EV_EBITDA")
    }
    assert {ref.financial_source_ids for ref in by_metric["PER"]} == {(2,)}
    assert {ref.source_id for ref in by_metric["PER"]} == {market_source_other.id}
    assert {
        ref.security_id for ref in by_metric["PER"] if ref.security_id != target.id
    } == {*peers, securities[4].id}
    for code in ("PBR", "EV_EBITDA"):
        assert {ref.financial_source_ids for ref in by_metric[code]} == {(1,)}
        assert {ref.source_id for ref in by_metric[code]} == {market_source.id}
        assert {
            ref.security_id for ref in by_metric[code] if ref.security_id != target.id
        } == {*peers, securities[4].id}

    bad_peer_indexes = (5, 6, 7, 8, 9, 10)
    for index in bad_peer_indexes:
        result = run_score((securities[1].id, securities[2].id, securities[index].id))
        assert result.components[5].status.value == "UNAVAILABLE"
    # Real SQLite score repository persists the source-filtered peer audit.
    persisted = SQLAlchemyValueScoreRepository(session).list_by_security(target.id)
    assert len(persisted) == 6 + len(bad_peer_indexes)
    assert persisted[0].components[5].peer_security_ids == relative.peer_security_ids
    assert securities[5].id in {
        peer_id for peer_id, _ in persisted[1].components[5].excluded_peer_reasons
    }
    assert persisted[1].components[5] == with_incompatible_extra
