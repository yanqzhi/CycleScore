"""Application request contracts for historical valuation percentiles."""

from dataclasses import dataclass
from datetime import UTC, date, datetime

from cyclescope.domain.entities.normalized_earnings import (
    DepreciationAmortizationSignConvention,
    NormalizationMethod,
)
from cyclescope.domain.entities.valuation_percentile import (
    PercentileMetric,
    PercentilePolicy,
    ValuationLookbackPeriod,
    ValuationPercentileResult,
)
from cyclescope.domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class HistoricalValuationPercentileRequest:
    security_id: int
    metric: PercentileMetric
    lookback_period: ValuationLookbackPeriod
    as_of: datetime
    calendar_id: str
    market_source_id: int | None = None
    financial_source_id: int | None = None
    normalization_window_years: int = 5
    normalization_method: NormalizationMethod = NormalizationMethod.ARITHMETIC_MEAN
    da_sign_convention: DepreciationAmortizationSignConvention = (
        DepreciationAmortizationSignConvention.UNKNOWN
    )
    policy: PercentilePolicy = PercentilePolicy()

    def __post_init__(self) -> None:
        if self.security_id < 1:
            raise DomainValidationError("security_id must be positive.")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
        if not self.calendar_id.strip():
            raise DomainValidationError("calendar_id is required for trading coverage.")
        for name in ("market_source_id", "financial_source_id"):
            source_id = getattr(self, name)
            if source_id is not None and source_id < 1:
                raise DomainValidationError(f"{name} must be positive when supplied.")
        if self.normalization_window_years not in {5, 7, 10}:
            raise DomainValidationError("Normalization window must be 5, 7, or 10.")


@dataclass(frozen=True, slots=True)
class HistoricalValuationPercentileResponse:
    result: ValuationPercentileResult


@dataclass(frozen=True, slots=True)
class HistoricalValuationPercentileQuery:
    security_id: int
    as_of: datetime

    def __post_init__(self) -> None:
        if self.security_id < 1:
            raise DomainValidationError("security_id must be positive.")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class HistoricalValuationPercentileListResponse:
    results: tuple[ValuationPercentileResult, ...]


def lookback_start(
    period: ValuationLookbackPeriod, as_of: datetime, listing_date: date | None
) -> date | None:
    """Return inclusive start date for calendar-year lookbacks."""
    end = as_of.astimezone(UTC).date()
    years = {
        ValuationLookbackPeriod.THREE_YEARS: 3,
        ValuationLookbackPeriod.FIVE_YEARS: 5,
        ValuationLookbackPeriod.TEN_YEARS: 10,
    }.get(period)
    if years is None:
        return listing_date
    try:
        start = end.replace(year=end.year - years)
    except ValueError:
        start = end.replace(year=end.year - years, day=28)
    return max(start, listing_date) if listing_date else start
