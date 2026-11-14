"""Immutable historical valuation percentile contracts."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from cyclescope.domain.entities.valuation import (
    ValuationInputReference,
    ValuationResultStatus,
)
from cyclescope.domain.exceptions import DomainValidationError


class PercentileMetric(StrEnum):
    PER = "PER"
    PBR = "PBR"
    EV_EBITDA = "EV_EBITDA"
    NORMALIZED_PER = "NORMALIZED_PER"
    NORMALIZED_EV_EBITDA = "NORMALIZED_EV_EBITDA"


class ValuationLookbackPeriod(StrEnum):
    THREE_YEARS = "3Y"
    FIVE_YEARS = "5Y"
    TEN_YEARS = "10Y"
    AVAILABLE_HISTORY = "AVAILABLE_HISTORY"


class PercentileMethod(StrEnum):
    ECDF = "ECDF"


class ValuationPercentileStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID_INPUT = "INVALID_INPUT"
    UNAVAILABLE = "UNAVAILABLE"


class PercentileConfidence(StrEnum):
    INSUFFICIENT = "INSUFFICIENT"
    LOW = "LOW_CONFIDENCE"
    MEDIUM = "MEDIUM_CONFIDENCE"
    HIGH = "HIGH_CONFIDENCE"


@dataclass(frozen=True, slots=True)
class PercentilePolicy:
    """Configurable count and coverage thresholds for report availability."""

    minimum_observations: int = 20
    medium_observations: int = 60
    high_observations: int = 120
    confidence_coverage: Decimal = Decimal("0.8")

    def __post_init__(self) -> None:
        if not (
            1
            <= self.minimum_observations
            <= self.medium_observations
            <= self.high_observations
        ):
            raise DomainValidationError(
                "Percentile observation thresholds are invalid."
            )
        if not self.confidence_coverage.is_finite() or not (
            0 <= self.confidence_coverage <= 1
        ):
            raise DomainValidationError("Confidence coverage must be in [0, 1].")


@dataclass(frozen=True, slots=True)
class HistoricalValuationObservation:
    """One PIT valuation snapshot; invalid snapshots retain their reason."""

    observation_date: date
    as_of: datetime
    status: str
    value: Decimal | None
    currency: str | None
    unit: str
    financial_period: str | None
    calculation_version: int
    market_source_id: int | None
    financial_source_ids: tuple[int, ...]
    snapshot_id: int | None = None
    normalized_earnings_result_id: int | None = None
    references: tuple[ValuationInputReference, ...] = ()
    unavailable_reason: str | None = None
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DomainValidationError("Observation as_of must be timezone-aware.")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
        if self.status not in {status.value for status in ValuationResultStatus}:
            raise DomainValidationError("Observation status is unsupported.")
        if self.calculation_version < 1:
            raise DomainValidationError("Calculation version must be positive.")
        if (self.status == "AVAILABLE") != (self.value is not None):
            raise DomainValidationError("Observation status and value conflict.")
        if self.value is not None and not self.value.is_finite():
            raise DomainValidationError("Observation value must be finite.")
        if self.currency is not None and (
            len(self.currency) != 3
            or not self.currency.isalpha()
            or not self.currency.isupper()
        ):
            raise DomainValidationError("Observation currency is invalid.")


@dataclass(frozen=True, slots=True)
class PercentileObservationAudit:
    """Audit record for one used, rejected, or duplicate observation."""

    observation_date: date
    value: Decimal | None
    included: bool
    reason: str | None
    snapshot_id: int | None
    normalized_earnings_result_id: int | None
    market_source_id: int | None
    financial_source_ids: tuple[int, ...]
    references: tuple[ValuationInputReference, ...]

    def __post_init__(self) -> None:
        if self.value is not None and not self.value.is_finite():
            raise DomainValidationError("Audited observation value must be finite.")
        if self.included == (self.reason is not None):
            raise DomainValidationError(
                "Included observations have no reason; excluded ones require one."
            )
        if self.snapshot_id is None and self.normalized_earnings_result_id is None:
            raise DomainValidationError("Audit requires a source snapshot reference.")


@dataclass(frozen=True, slots=True)
class ValuationPercentileResult:
    """One immutable percentile assessment and complete observation audit."""

    security_id: int
    company_id: int
    metric: PercentileMetric
    lookback_period: ValuationLookbackPeriod
    method: PercentileMethod
    as_of: datetime
    observation_start: date | None
    observation_end: date | None
    current_value: Decimal | None
    percentile: Decimal | None
    historical_minimum: Decimal | None
    historical_maximum: Decimal | None
    historical_median: Decimal | None
    valid_observations: int
    excluded_observations: int
    expected_observations: int | None
    coverage_ratio: Decimal | None
    status: ValuationPercentileStatus
    confidence: PercentileConfidence
    data_quality: str
    currency: str | None
    unit: str
    financial_period: str | None
    calculation_version: int
    status_reason: str | None
    observations: tuple[PercentileObservationAudit, ...]
    created_at: datetime | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if self.security_id < 1 or self.company_id < 1 or self.calculation_version < 1:
            raise DomainValidationError("Percentile result identity is invalid.")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
        if self.valid_observations < 0 or self.excluded_observations < 0:
            raise DomainValidationError("Observation counts cannot be negative.")
        if self.expected_observations is not None and self.expected_observations < 0:
            raise DomainValidationError("Expected observations cannot be negative.")
        if self.coverage_ratio is not None and (
            not self.coverage_ratio.is_finite() or not 0 <= self.coverage_ratio <= 1
        ):
            raise DomainValidationError("Coverage ratio must be in [0, 1].")
        if self.coverage_ratio is not None and not self.expected_observations:
            raise DomainValidationError(
                "Coverage requires a positive expected observation count."
            )
        if (self.status == ValuationPercentileStatus.AVAILABLE) != (
            self.percentile is not None
        ):
            raise DomainValidationError("Percentile status and value conflict.")
        if self.status == ValuationPercentileStatus.AVAILABLE and (
            self.current_value is None or self.valid_observations < 1
        ):
            raise DomainValidationError(
                "Available percentile requires a current value and historical samples."
            )
        for value in (
            self.current_value,
            self.percentile,
            self.historical_minimum,
            self.historical_maximum,
            self.historical_median,
        ):
            if value is not None and not value.is_finite():
                raise DomainValidationError("Percentile result values must be finite.")
        if self.percentile is not None and not 0 <= self.percentile <= 100:
            raise DomainValidationError("Percentile must be between 0 and 100.")
        if (
            self.status == ValuationPercentileStatus.AVAILABLE
            and self.current_value is not None
            and self.current_value <= 0
        ):
            raise DomainValidationError("Current valuation must be positive.")
        if self.currency is not None and (
            len(self.currency) != 3
            or not self.currency.isalpha()
            or not self.currency.isupper()
        ):
            raise DomainValidationError("Percentile currency is invalid.")
        if self.unit != "RATIO":
            raise DomainValidationError("Valuation percentile unit must be RATIO.")
        if (
            self.observation_start is not None
            and self.observation_end is not None
            and self.observation_start > self.observation_end
        ):
            raise DomainValidationError("Observation period bounds are invalid.")
        if sum(item.included for item in self.observations) != self.valid_observations:
            raise DomainValidationError(
                "Valid observation count does not match audit rows."
            )
        if (
            sum(not item.included for item in self.observations)
            != self.excluded_observations
        ):
            raise DomainValidationError(
                "Excluded observation count does not match audit rows."
            )
        if (
            self.status != ValuationPercentileStatus.AVAILABLE
            and not self.status_reason
        ):
            raise DomainValidationError(
                "Non-available percentile results need a reason."
            )
        if self.created_at is not None:
            if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
                raise DomainValidationError("created_at must be timezone-aware.")
            object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))
