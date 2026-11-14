from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from cyclescope.application.dto.value_score import CalculateValueScoreRequest
from cyclescope.application.use_cases.value_score import CalculateValueScore
from cyclescope.domain.entities.valuation_percentile import (
    PercentileMetric,
    ValuationLookbackPeriod,
)
from cyclescope.domain.exceptions import DomainValidationError


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
    def __init__(self):
        self.requests = []

    def execute(self, request):
        self.requests.append(request)
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


class _InputBuilder:
    def execute(self, request):
        raise DomainValidationError("No source-scoped balance sheet is available.")


class _ScoreRepo:
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
