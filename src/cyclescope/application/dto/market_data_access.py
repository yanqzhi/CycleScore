"""Typed application contracts for point-in-time market-data reads."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import TypeVar

from cyclescope.domain.entities.daily_price import DailyPrice
from cyclescope.domain.entities.fx_rate import FxRate
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.market_data import CurrencyPair


def _normalize_as_of(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise DomainValidationError("as_of must be timezone-aware.")
    return value.astimezone(UTC)


def _validate_date(value: date, field_name: str) -> None:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise DomainValidationError(f"{field_name} must be a calendar date.")


def _validate_source(source_id: int | None) -> None:
    if source_id is not None and (
        not isinstance(source_id, int) or isinstance(source_id, bool) or source_id < 1
    ):
        raise DomainValidationError("source_id must be positive when supplied.")


def _validate_limit(limit: int, field_name: str) -> None:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise DomainValidationError(f"{field_name} must be positive.")


@dataclass(frozen=True, slots=True)
class PriceQueryScope:
    security_id: int
    source_id: int | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.security_id, int)
            or isinstance(self.security_id, bool)
            or self.security_id < 1
        ):
            raise DomainValidationError("security_id must be positive.")
        _validate_source(self.source_id)


@dataclass(frozen=True, slots=True)
class FxQueryScope:
    base_currency: str
    quote_currency: str
    source_id: int | None = None

    def __post_init__(self) -> None:
        pair = CurrencyPair(
            self.base_currency.strip().upper(), self.quote_currency.strip().upper()
        )
        object.__setattr__(self, "base_currency", pair.base_currency)
        object.__setattr__(self, "quote_currency", pair.quote_currency)
        _validate_source(self.source_id)


@dataclass(frozen=True, slots=True)
class LatestPriceRequest:
    scope: PriceQueryScope
    as_of: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _normalize_as_of(self.as_of))


@dataclass(frozen=True, slots=True)
class LatestFxRateRequest:
    scope: FxQueryScope
    as_of: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _normalize_as_of(self.as_of))


@dataclass(frozen=True, slots=True)
class PricePeriodRequest:
    scope: PriceQueryScope
    start_date: date
    end_date: date
    as_of: datetime
    minimum_observations: int = 1

    def __post_init__(self) -> None:
        _validate_period(self.start_date, self.end_date, self.minimum_observations)
        object.__setattr__(self, "as_of", _normalize_as_of(self.as_of))


@dataclass(frozen=True, slots=True)
class FxPeriodRequest:
    scope: FxQueryScope
    start_date: date
    end_date: date
    as_of: datetime
    minimum_observations: int = 1

    def __post_init__(self) -> None:
        _validate_period(self.start_date, self.end_date, self.minimum_observations)
        object.__setattr__(self, "as_of", _normalize_as_of(self.as_of))


@dataclass(frozen=True, slots=True)
class PrecedingPricesRequest:
    scope: PriceQueryScope
    before_date: date
    as_of: datetime
    limit_per_source: int = 20

    def __post_init__(self) -> None:
        _validate_date(self.before_date, "before_date")
        _validate_limit(self.limit_per_source, "limit_per_source")
        object.__setattr__(self, "as_of", _normalize_as_of(self.as_of))


@dataclass(frozen=True, slots=True)
class PrecedingFxRatesRequest:
    scope: FxQueryScope
    before_date: date
    as_of: datetime
    limit_per_source: int = 20

    def __post_init__(self) -> None:
        _validate_date(self.before_date, "before_date")
        _validate_limit(self.limit_per_source, "limit_per_source")
        object.__setattr__(self, "as_of", _normalize_as_of(self.as_of))


@dataclass(frozen=True, slots=True)
class PriceObservationAsOfRequest:
    scope: PriceQueryScope
    observation_date: date
    as_of: datetime

    def __post_init__(self) -> None:
        _validate_date(self.observation_date, "observation_date")
        object.__setattr__(self, "as_of", _normalize_as_of(self.as_of))


@dataclass(frozen=True, slots=True)
class FxObservationAsOfRequest:
    scope: FxQueryScope
    observation_date: date
    as_of: datetime

    def __post_init__(self) -> None:
        _validate_date(self.observation_date, "observation_date")
        object.__setattr__(self, "as_of", _normalize_as_of(self.as_of))


@dataclass(frozen=True, slots=True)
class PriceRevisionHistoryRequest:
    scope: PriceQueryScope
    observation_date: date
    as_of: datetime

    def __post_init__(self) -> None:
        _validate_date(self.observation_date, "observation_date")
        if self.scope.source_id is None:
            raise DomainValidationError(
                "Price revision history requires an explicit source_id."
            )
        object.__setattr__(self, "as_of", _normalize_as_of(self.as_of))


@dataclass(frozen=True, slots=True)
class FxRevisionHistoryRequest:
    scope: FxQueryScope
    observation_date: date
    as_of: datetime

    def __post_init__(self) -> None:
        _validate_date(self.observation_date, "observation_date")
        if self.scope.source_id is None:
            raise DomainValidationError(
                "FX revision history requires an explicit source_id."
            )
        object.__setattr__(self, "as_of", _normalize_as_of(self.as_of))


class DataRetrievalStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    NO_DATA = "NO_DATA"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class SourceDataAvailability:
    source_id: int
    latest_observation_date: date | None
    latest_available_at: datetime | None
    period_observation_count: int
    period_contains_data: bool
    status: DataRetrievalStatus

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_id, int)
            or isinstance(self.source_id, bool)
            or self.source_id < 1
            or not isinstance(self.period_observation_count, int)
            or isinstance(self.period_observation_count, bool)
            or self.period_observation_count < 0
        ):
            raise DomainValidationError(
                "Source availability identifiers/counts are invalid."
            )
        if self.period_contains_data != (self.period_observation_count > 0):
            raise DomainValidationError(
                "Period data flag must match its observation count."
            )
        if (self.period_observation_count == 0) != (
            self.status == DataRetrievalStatus.NO_DATA
        ):
            raise DomainValidationError("Retrieval status conflicts with period data.")
        if self.latest_available_at is not None:
            object.__setattr__(
                self, "latest_available_at", _normalize_as_of(self.latest_available_at)
            )
        if (self.latest_observation_date is None) != (self.latest_available_at is None):
            raise DomainValidationError(
                "Latest observation date and availability timestamp must be paired."
            )


ObservationT = TypeVar("ObservationT", DailyPrice, FxRate)


@dataclass(frozen=True, slots=True)
class MarketDataQueryResult[ObservationT]:
    """Typed observations plus the exact cutoff and optional period coverage."""

    as_of: datetime
    observations: tuple[ObservationT, ...]
    availability: tuple[SourceDataAvailability, ...] = ()
    start_date: date | None = None
    end_date: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _normalize_as_of(self.as_of))


def _validate_period(start: date, end: date, minimum_observations: int) -> None:
    _validate_date(start, "start_date")
    _validate_date(end, "end_date")
    if start > end:
        raise DomainValidationError("start_date must be on or before end_date.")
    if (
        not isinstance(minimum_observations, int)
        or isinstance(minimum_observations, bool)
        or minimum_observations < 1
    ):
        raise DomainValidationError("minimum_observations must be positive.")
