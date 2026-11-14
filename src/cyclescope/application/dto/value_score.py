"""Application request/response DTOs for Value Score."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from cyclescope.domain.entities.normalized_earnings import (
    DepreciationAmortizationSignConvention,
    NormalizationMethod,
)
from cyclescope.domain.entities.valuation_percentile import (
    PercentilePolicy,
    ValuationLookbackPeriod,
)
from cyclescope.domain.entities.value_score import ValueScore, ValueScoreConfig
from cyclescope.domain.exceptions import DomainValidationError


class HistoricalPriceBasis(StrEnum):
    CLOSE = "CLOSE"
    ADJUSTED_CLOSE = "ADJUSTED_CLOSE"


@dataclass(frozen=True, slots=True)
class CalculateValueScoreRequest:
    security_id: int
    as_of: datetime
    calendar_id: str
    lookback_period: ValuationLookbackPeriod = ValuationLookbackPeriod.FIVE_YEARS
    market_source_id: int | None = None
    financial_source_id: int | None = None
    price_basis: HistoricalPriceBasis = HistoricalPriceBasis.ADJUSTED_CLOSE
    peer_security_ids: tuple[int, ...] = ()
    normalization_window_years: int = 5
    normalization_method: NormalizationMethod = NormalizationMethod.ARITHMETIC_MEAN
    da_sign_convention: DepreciationAmortizationSignConvention = (
        DepreciationAmortizationSignConvention.UNKNOWN
    )
    percentile_policy: PercentilePolicy = PercentilePolicy()
    config: ValueScoreConfig = ValueScoreConfig()

    def __post_init__(self) -> None:
        if self.security_id < 1:
            raise DomainValidationError("security_id must be positive.")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
        if not self.calendar_id.strip():
            raise DomainValidationError("calendar_id is required.")
        for field_name in ("market_source_id", "financial_source_id"):
            source_id = getattr(self, field_name)
            if source_id is not None and source_id < 1:
                raise DomainValidationError(f"{field_name} must be positive.")
        if len(self.peer_security_ids) != len(set(self.peer_security_ids)):
            raise DomainValidationError(
                "Peer security IDs must not contain duplicates."
            )
        if any(peer < 1 or peer == self.security_id for peer in self.peer_security_ids):
            raise DomainValidationError("Peer security IDs are invalid.")
        if self.normalization_window_years not in {5, 7, 10}:
            raise DomainValidationError("Normalization window must be 5, 7, or 10.")


@dataclass(frozen=True, slots=True)
class ValueScoreResponse:
    score: ValueScore
