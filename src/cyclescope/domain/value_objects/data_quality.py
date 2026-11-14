"""Stable domain vocabulary for market-data assessment and anomaly lifecycle."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from cyclescope.domain.exceptions import DomainValidationError


class DatasetType(StrEnum):
    DAILY_PRICE = "DAILY_PRICE"
    FX_RATE = "FX_RATE"


class QualityStatus(StrEnum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CalendarStatus(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN_CALENDAR = "UNKNOWN_CALENDAR"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class QualityComponentStatus(StrEnum):
    PASSED = "PASSED"
    WARNING = "WARNING"
    FAILED = "FAILED"
    UNAVAILABLE = "UNAVAILABLE"


class AnomalySeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AnomalyStatus(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class AnomalyType(StrEnum):
    DUPLICATE_EXACT = "DUPLICATE_EXACT"
    DUPLICATE_CONFLICT = "DUPLICATE_CONFLICT"
    MISSING_SESSION = "MISSING_SESSION"
    PRICE_MOVE = "PRICE_MOVE"
    FX_MOVE = "FX_MOVE"
    ABNORMAL_VOLUME = "ABNORMAL_VOLUME"
    OHLC_INCONSISTENCY = "OHLC_INCONSISTENCY"
    DISCONTINUITY = "DISCONTINUITY"


@dataclass(frozen=True, slots=True)
class QualityComponent:
    name: str
    score: Decimal | None
    weight: Decimal
    status: QualityComponentStatus
    explanation: str

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.explanation.strip():
            raise DomainValidationError(
                "Quality component name and explanation are required."
            )
        if not self.weight.is_finite() or self.weight < 0:
            raise DomainValidationError(
                "Quality component weight must be non-negative."
            )
        if self.score is not None and (
            not self.score.is_finite() or self.score < 0 or self.score > 100
        ):
            raise DomainValidationError(
                "Quality component score must be between 0 and 100."
            )
        if (self.score is None) != (self.status == QualityComponentStatus.UNAVAILABLE):
            raise DomainValidationError("Unavailable components must not have a score.")


@dataclass(frozen=True, slots=True)
class QualityDateRange:
    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise DomainValidationError("Quality date range start must not follow end.")


@dataclass(frozen=True, slots=True)
class DataQualityConfig:
    """Versioned scoring and outlier thresholds; percentages are decimal ratios."""

    version: str = "market-quality-v1"
    price_move_threshold: Decimal = Decimal("0.20")
    fx_move_threshold: Decimal = Decimal("0.05")
    volume_median_multiple: Decimal = Decimal("5")
    weights: tuple[tuple[str, Decimal], ...] = (
        ("completeness", Decimal("0.30")),
        ("structural_validity", Decimal("0.25")),
        ("consistency", Decimal("0.20")),
        ("outlier_assessment", Decimal("0.15")),
        ("provenance", Decimal("0.10")),
    )

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise DomainValidationError("Scoring configuration version is required.")
        if self.price_move_threshold <= 0 or self.fx_move_threshold <= 0:
            raise DomainValidationError("Move thresholds must be positive.")
        if self.volume_median_multiple <= 1:
            raise DomainValidationError(
                "Volume threshold must exceed one times median."
            )
        if sum((weight for _, weight in self.weights), Decimal(0)) != Decimal(1):
            raise DomainValidationError("Scoring weights must sum exactly to 1.")
        if any(weight < 0 for _, weight in self.weights):
            raise DomainValidationError("Scoring weights cannot be negative.")
