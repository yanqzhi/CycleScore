"""Validation for provider-independent market-data read contracts."""

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from cyclescope.application.dto.market_data_access import (
    FxPeriodRequest,
    FxQueryScope,
    FxRevisionHistoryRequest,
    PricePeriodRequest,
    PriceQueryScope,
    PriceRevisionHistoryRequest,
)
from cyclescope.domain.exceptions import DomainValidationError


def test_query_scopes_validate_identifiers_and_normalize_fx_pair():
    with pytest.raises(DomainValidationError, match="security_id"):
        PriceQueryScope(0)
    with pytest.raises(DomainValidationError, match="source_id"):
        PriceQueryScope(1, 0)

    fx_scope = FxQueryScope(" usd ", "jpy")
    assert (fx_scope.base_currency, fx_scope.quote_currency) == ("USD", "JPY")
    with pytest.raises(DomainValidationError, match="different"):
        FxQueryScope("usd", "USD")


def test_period_requests_validate_range_minimum_and_timezone():
    scope = PriceQueryScope(1)
    now = datetime(2026, 5, 15, tzinfo=UTC)
    with pytest.raises(DomainValidationError, match="on or before"):
        PricePeriodRequest(scope, date(2026, 5, 16), date(2026, 5, 15), now)
    with pytest.raises(DomainValidationError, match="minimum_observations"):
        FxPeriodRequest(
            FxQueryScope("USD", "JPY"), date(2026, 5, 1), date(2026, 5, 2), now, 0
        )
    with pytest.raises(DomainValidationError, match="timezone-aware"):
        PricePeriodRequest(
            scope,
            date(2026, 5, 1),
            date(2026, 5, 2),
            datetime(2026, 5, 15),
        )


@pytest.mark.parametrize(
    "request_type,scope_type,scope_args",
    [
        (PriceRevisionHistoryRequest, PriceQueryScope, (1,)),
        (FxRevisionHistoryRequest, FxQueryScope, ("USD", "JPY")),
    ],
)
def test_revision_history_requires_explicit_source(
    request_type, scope_type, scope_args
):
    request_date = date(2026, 5, 14)
    as_of = datetime(2026, 5, 15, tzinfo=UTC)
    with pytest.raises(DomainValidationError, match="explicit source_id"):
        request_type(scope_type(*scope_args), request_date, as_of)


def test_revision_history_normalizes_as_of_to_utc():
    request = PriceRevisionHistoryRequest(
        PriceQueryScope(1, 7),
        date(2026, 5, 14),
        datetime(2026, 5, 15, 17, tzinfo=timezone(timedelta(hours=9))),
    )
    assert request.as_of == datetime(2026, 5, 15, 8, tzinfo=UTC)
