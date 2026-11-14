"""Point-in-time query integration tests against SQLite repositories."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from cyclescope.application.dto.market_data_access import (
    DataRetrievalStatus,
    FxObservationAsOfRequest,
    FxPeriodRequest,
    FxQueryScope,
    FxRevisionHistoryRequest,
    LatestFxRateRequest,
    LatestPriceRequest,
    PrecedingPricesRequest,
    PriceObservationAsOfRequest,
    PricePeriodRequest,
    PriceQueryScope,
    PriceRevisionHistoryRequest,
)
from cyclescope.application.use_cases.market_data_access import MarketDataAccess
from cyclescope.domain.entities import DailyPrice, FxRate
from cyclescope.domain.value_objects.market_data import CurrencyPair
from cyclescope.infrastructure.database.models import (
    CompanyModel,
    DataSourceModel,
    SecurityModel,
)
from cyclescope.infrastructure.database.repositories.market_data import (
    SQLAlchemyDailyPriceRepository,
    SQLAlchemyFxRateRepository,
)

AS_OF = datetime(2026, 5, 15, 16, tzinfo=UTC)


def _references(session: Session) -> tuple[int, int, int, int]:
    company = CompanyModel(name="Query company", country_code="US")
    sources = [
        DataSourceModel(code="QUERY_A", name="Query A", provider_type="test"),
        DataSourceModel(code="QUERY_B", name="Query B", provider_type="test"),
        DataSourceModel(code="QUERY_EMPTY", name="Empty source", provider_type="test"),
    ]
    session.add_all([company, *sources])
    session.flush()
    security = SecurityModel(company_id=company.id, security_type="common_stock")
    session.add(security)
    session.flush()
    return security.id, sources[0].id, sources[1].id, sources[2].id


def _price(
    security_id: int,
    source_id: int,
    day: date,
    revision: int,
    close: str,
    available_at: datetime,
    collected_at: datetime,
) -> DailyPrice:
    value = Decimal(close)
    return DailyPrice(
        security_id=security_id,
        observation_date=day,
        open=value,
        high=value,
        low=value,
        close=value,
        adjusted_close=None,
        volume=100,
        currency="USD",
        source_id=source_id,
        publication_date=None,
        available_at=available_at,
        collected_at=collected_at,
        revision_number=revision,
        created_at=available_at,
        updated_at=available_at,
    )


def _fx(
    source_id: int,
    day: date,
    revision: int,
    rate: str,
    available_at: datetime,
    collected_at: datetime,
) -> FxRate:
    return FxRate(
        base_currency="USD",
        quote_currency="JPY",
        observation_date=day,
        rate=Decimal(rate),
        source_id=source_id,
        publication_date=None,
        available_at=available_at,
        collected_at=collected_at,
        revision_number=revision,
        created_at=available_at,
        updated_at=available_at,
    )


def _access(session: Session) -> tuple[MarketDataAccess, int, int, int, int]:
    security_id, source_a, source_b, empty_source = _references(session)
    prices = SQLAlchemyDailyPriceRepository(session)
    fx = SQLAlchemyFxRateRepository(session)
    first_day = date(2026, 5, 14)
    report_day = date(2026, 5, 15)
    prices.save(
        _price(
            security_id,
            source_a,
            first_day,
            1,
            "10",
            AS_OF - timedelta(days=1),
            AS_OF - timedelta(days=2),
        )
    )
    # Equal availability timestamps still select the higher eligible revision.
    prices.save(
        _price(
            security_id,
            source_a,
            first_day,
            2,
            "11",
            AS_OF - timedelta(days=1),
            AS_OF - timedelta(hours=1),
        )
    )
    # Collected before as_of does not make this later revision visible.
    prices.save(
        _price(
            security_id,
            source_a,
            first_day,
            3,
            "13",
            AS_OF + timedelta(seconds=1),
            AS_OF - timedelta(hours=2),
        )
    )
    # Available by the cutoff despite a later collection timestamp.
    prices.save(
        _price(
            security_id,
            source_a,
            report_day,
            1,
            "12",
            AS_OF - timedelta(minutes=1),
            AS_OF + timedelta(days=1),
        )
    )
    prices.save(
        _price(
            security_id,
            source_b,
            first_day,
            1,
            "20",
            AS_OF - timedelta(days=1),
            AS_OF - timedelta(hours=1),
        )
    )
    # Observation date is future even though its availability timestamp is early.
    prices.save(
        _price(
            security_id,
            source_a,
            date(2026, 5, 16),
            1,
            "99",
            AS_OF - timedelta(days=1),
            AS_OF - timedelta(days=1),
        )
    )
    pair = CurrencyPair("USD", "JPY")
    fx.save(
        _fx(
            source_a,
            first_day,
            1,
            "150",
            AS_OF - timedelta(days=1),
            AS_OF - timedelta(hours=1),
        )
    )
    fx.save(
        _fx(
            source_a,
            first_day,
            2,
            "151",
            AS_OF + timedelta(seconds=1),
            AS_OF - timedelta(hours=2),
        )
    )
    fx.save(
        _fx(
            source_b,
            first_day,
            1,
            "160",
            AS_OF - timedelta(days=1),
            AS_OF - timedelta(hours=1),
        )
    )
    assert pair.base_currency == "USD"
    return MarketDataAccess(prices, fx), security_id, source_a, source_b, empty_source


def test_price_access_preserves_sources_revisions_and_as_of_rules(session: Session):
    access, security_id, source_a, source_b, empty_source = _access(session)
    scope = PriceQueryScope(security_id)
    period = access.get_prices_by_period_as_of(
        PricePeriodRequest(scope, date(2026, 5, 14), date(2026, 5, 16), AS_OF)
    )
    assert [
        (row.observation_date, row.source_id, row.revision_number, row.close)
        for row in period.observations
    ] == [
        (date(2026, 5, 14), source_a, 2, Decimal("11.00000000")),
        (date(2026, 5, 14), source_b, 1, Decimal("20.00000000")),
        (date(2026, 5, 15), source_a, 1, Decimal("12.00000000")),
    ]
    assert period.as_of == AS_OF
    assert (period.start_date, period.end_date) == (
        date(2026, 5, 14),
        date(2026, 5, 16),
    )
    by_source = {item.source_id: item for item in period.availability}
    assert by_source[source_a].period_observation_count == 2
    assert by_source[source_a].status == DataRetrievalStatus.AVAILABLE
    assert by_source[source_a].latest_observation_date == date(2026, 5, 15)
    assert by_source[source_a].latest_available_at == AS_OF - timedelta(minutes=1)
    assert by_source[source_b].period_observation_count == 1
    assert by_source[source_b].status == DataRetrievalStatus.AVAILABLE

    latest = access.get_latest_available_prices(LatestPriceRequest(scope, AS_OF))
    assert [(row.source_id, row.observation_date) for row in latest.observations] == [
        (source_a, date(2026, 5, 15)),
        (source_b, date(2026, 5, 14)),
    ]
    point = access.get_price_observation_as_of(
        PriceObservationAsOfRequest(scope, date(2026, 5, 14), AS_OF)
    )
    assert {row.source_id for row in point.observations} == {source_a, source_b}
    future_point = access.get_price_observation_as_of(
        PriceObservationAsOfRequest(scope, date(2026, 5, 16), AS_OF)
    )
    assert future_point.observations == ()

    revisions = access.get_price_revision_history(
        PriceRevisionHistoryRequest(
            PriceQueryScope(security_id, source_a), date(2026, 5, 14), AS_OF
        )
    )
    assert [row.revision_number for row in revisions.observations] == [1, 2]
    later = access.get_price_revision_history(
        PriceRevisionHistoryRequest(
            PriceQueryScope(security_id, source_a),
            date(2026, 5, 14),
            AS_OF + timedelta(minutes=1),
        )
    )
    assert [row.revision_number for row in later.observations] == [1, 2, 3]

    empty = access.get_prices_by_period_as_of(
        PricePeriodRequest(
            PriceQueryScope(security_id, empty_source),
            date(2026, 5, 14),
            date(2026, 5, 15),
            AS_OF,
        )
    )
    assert empty.observations == ()
    assert empty.availability[0].status == DataRetrievalStatus.NO_DATA
    assert empty.availability[0].latest_observation_date is None

    insufficient = access.get_prices_by_period_as_of(
        PricePeriodRequest(
            PriceQueryScope(security_id, source_b),
            date(2026, 5, 14),
            date(2026, 5, 14),
            AS_OF,
            minimum_observations=2,
        )
    )
    assert insufficient.availability[0].status == DataRetrievalStatus.INSUFFICIENT_DATA

    preceding = access.get_preceding_prices(
        PrecedingPricesRequest(scope, date(2026, 5, 15), AS_OF, limit_per_source=1)
    )
    assert [
        (row.source_id, row.observation_date) for row in preceding.observations
    ] == [
        (source_a, date(2026, 5, 14)),
        (source_b, date(2026, 5, 14)),
    ]


def test_fx_access_uses_the_same_point_in_time_rules(session: Session):
    access, _, source_a, source_b, _ = _access(session)
    scope = FxQueryScope("usd", "jpy")
    result = access.get_fx_rates_by_period_as_of(
        FxPeriodRequest(scope, date(2026, 5, 14), date(2026, 5, 15), AS_OF)
    )
    assert [
        (row.source_id, row.rate, row.revision_number) for row in result.observations
    ] == [
        (source_a, Decimal("150.000000000000"), 1),
        (source_b, Decimal("160.000000000000"), 1),
    ]
    latest = access.get_latest_available_fx_rates(LatestFxRateRequest(scope, AS_OF))
    assert [(row.source_id, row.rate) for row in latest.observations] == [
        (source_a, Decimal("150.000000000000")),
        (source_b, Decimal("160.000000000000")),
    ]
    point = access.get_fx_observation_as_of(
        FxObservationAsOfRequest(scope, date(2026, 5, 14), AS_OF)
    )
    assert len(point.observations) == 2
    history = access.get_fx_revision_history(
        FxRevisionHistoryRequest(
            FxQueryScope("USD", "JPY", source_a), date(2026, 5, 14), AS_OF
        )
    )
    assert [row.revision_number for row in history.observations] == [1]
