"""Typed requests for assembling valuation inputs at a historical cutoff."""

from dataclasses import dataclass
from datetime import UTC, date, datetime

from cyclescope.domain.entities.valuation import ValuationMetricValue
from cyclescope.domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class ValuationInputRequest:
    security_id: int
    valuation_date: date
    as_of: datetime
    financial_source_id: int | None = None
    market_source_id: int | None = None

    def __post_init__(self) -> None:
        if self.security_id < 1:
            raise DomainValidationError("security_id must be positive.")
        if isinstance(self.valuation_date, datetime):
            raise DomainValidationError("valuation_date must be a calendar date.")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
        if self.valuation_date != self.as_of.date():
            raise DomainValidationError(
                "valuation_date must match the UTC date of as_of."
            )
        for name in ("financial_source_id", "market_source_id"):
            source_id = getattr(self, name)
            if source_id is not None and source_id < 1:
                raise DomainValidationError(f"{name} must be positive when supplied.")


@dataclass(frozen=True, slots=True)
class ValuationDateQuery:
    security_id: int
    valuation_date: date
    as_of: datetime | None = None

    def __post_init__(self) -> None:
        _validate_query(self.security_id, self.valuation_date)
        if self.as_of is not None:
            if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
                raise DomainValidationError("as_of must be timezone-aware.")
            object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
            if self.valuation_date > self.as_of.date():
                raise DomainValidationError(
                    "valuation_date cannot follow as_of UTC date."
                )


@dataclass(frozen=True, slots=True)
class ValuationRangeQuery:
    security_id: int
    start_date: date
    end_date: date
    as_of: datetime | None = None

    def __post_init__(self) -> None:
        _validate_query(self.security_id, self.start_date)
        _validate_query(self.security_id, self.end_date)
        if self.start_date > self.end_date:
            raise DomainValidationError("start_date must not follow end_date.")
        if self.as_of is not None:
            if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
                raise DomainValidationError("as_of must be timezone-aware.")
            object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
            if self.end_date > self.as_of.date():
                raise DomainValidationError("end_date cannot follow as_of UTC date.")


@dataclass(frozen=True, slots=True)
class ValuationSnapshotQuery:
    security_id: int
    as_of: datetime
    start_date: date | None = None
    end_date: date | None = None

    def __post_init__(self) -> None:
        if self.security_id < 1:
            raise DomainValidationError("security_id must be positive.")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
        if self.start_date is not None:
            _validate_query(self.security_id, self.start_date)
        if self.end_date is not None:
            _validate_query(self.security_id, self.end_date)
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.start_date > self.end_date
        ):
            raise DomainValidationError("start_date must not follow end_date.")
        if self.end_date is not None and self.end_date > self.as_of.date():
            raise DomainValidationError("end_date cannot follow as_of UTC date.")


@dataclass(frozen=True, slots=True)
class ValuationSnapshotResponse:
    snapshots: tuple[ValuationMetricValue, ...]


def _validate_query(security_id: int, value: date) -> None:
    if security_id < 1:
        raise DomainValidationError("security_id must be positive.")
    if isinstance(value, datetime):
        raise DomainValidationError("valuation dates must be calendar dates.")
