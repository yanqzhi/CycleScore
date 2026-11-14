"""Versioned Value Score contracts and provenance records."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from cyclescope.domain.exceptions import DomainValidationError


class ValueScoreComponentCode(StrEnum):
    HISTORICAL_PRICE = "HISTORICAL_PRICE"
    HISTORICAL_VALUATION = "HISTORICAL_VALUATION"
    NORMALIZED_EARNINGS_VALUATION = "NORMALIZED_EARNINGS_VALUATION"
    CASH_FLOW_VALUATION = "CASH_FLOW_VALUATION"
    BALANCE_SHEET = "BALANCE_SHEET"
    RELATIVE_VALUATION = "RELATIVE_VALUATION"


class ValueScoreStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ValueScoreConfidence(StrEnum):
    INSUFFICIENT = "INSUFFICIENT"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ValueScoreComponentStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_INPUT = "INVALID_INPUT"


DEFAULT_VALUE_SCORE_WEIGHTS = (
    (ValueScoreComponentCode.HISTORICAL_PRICE, Decimal("0.15")),
    (ValueScoreComponentCode.HISTORICAL_VALUATION, Decimal("0.20")),
    (ValueScoreComponentCode.NORMALIZED_EARNINGS_VALUATION, Decimal("0.25")),
    (ValueScoreComponentCode.CASH_FLOW_VALUATION, Decimal("0.15")),
    (ValueScoreComponentCode.BALANCE_SHEET, Decimal("0.15")),
    (ValueScoreComponentCode.RELATIVE_VALUATION, Decimal("0.10")),
)


@dataclass(frozen=True, slots=True)
class ValueScoreConfig:
    """Scoring weights and thresholds; changing any field requires a new version."""

    version: int = 1
    weights: tuple[tuple[ValueScoreComponentCode, Decimal], ...] = (
        DEFAULT_VALUE_SCORE_WEIGHTS
    )
    minimum_coverage: Decimal = Decimal("0.65")
    medium_confidence_coverage: Decimal = Decimal("0.75")
    high_confidence_coverage: Decimal = Decimal("0.90")
    minimum_price_observations: int = 20
    minimum_peer_count: int = 3
    maximum_debt_to_equity: Decimal = Decimal("2")

    def __post_init__(self) -> None:
        expected = set(ValueScoreComponentCode)
        codes = [code for code, _ in self.weights]
        if self.version < 1:
            raise DomainValidationError("Value Score config version must be positive.")
        if len(codes) != len(set(codes)) or set(codes) != expected:
            raise DomainValidationError(
                "Value Score weights must define each component exactly once."
            )
        if any(not weight.is_finite() or weight < 0 for _, weight in self.weights):
            raise DomainValidationError(
                "Value Score weights must be finite and non-negative."
            )
        if sum((weight for _, weight in self.weights), Decimal(0)) != Decimal(1):
            raise DomainValidationError("Value Score weights must total exactly 1.")
        for name in (
            "minimum_coverage",
            "medium_confidence_coverage",
            "high_confidence_coverage",
        ):
            value = getattr(self, name)
            if not value.is_finite() or not 0 <= value <= 1:
                raise DomainValidationError(f"{name} must be in [0, 1].")
        if not (
            self.minimum_coverage
            <= self.medium_confidence_coverage
            <= self.high_confidence_coverage
        ):
            raise DomainValidationError(
                "Value Score coverage thresholds are unordered."
            )
        if self.minimum_price_observations < 1 or self.minimum_peer_count < 1:
            raise DomainValidationError("Sample thresholds must be positive.")
        if (
            not self.maximum_debt_to_equity.is_finite()
            or self.maximum_debt_to_equity <= 0
        ):
            raise DomainValidationError("maximum_debt_to_equity must be positive.")

    @property
    def weight_map(self) -> dict[ValueScoreComponentCode, Decimal]:
        return dict(self.weights)

    def snapshot(self) -> dict[str, object]:
        return {
            "version": self.version,
            "weights": {code.value: str(weight) for code, weight in self.weights},
            "minimum_coverage": str(self.minimum_coverage),
            "medium_confidence_coverage": str(self.medium_confidence_coverage),
            "high_confidence_coverage": str(self.high_confidence_coverage),
            "minimum_price_observations": self.minimum_price_observations,
            "minimum_peer_count": self.minimum_peer_count,
            "maximum_debt_to_equity": str(self.maximum_debt_to_equity),
        }


@dataclass(frozen=True, slots=True)
class ValueScoreInputReference:
    """Provider-neutral reference to one input row or immutable calculation."""

    record_type: str
    record_id: int
    available_at: datetime
    source_id: int | None = None
    revision_number: int | None = None
    observation_date: date | None = None
    security_id: int | None = None
    reference_code: str | None = None
    financial_source_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not self.record_type.strip() or self.record_id < 1:
            raise DomainValidationError("Value Score input reference is invalid.")
        if self.source_id is not None and self.source_id < 1:
            raise DomainValidationError("Reference source_id must be positive.")
        if self.revision_number is not None and self.revision_number < 1:
            raise DomainValidationError("Reference revision must be positive.")
        if self.security_id is not None and self.security_id < 1:
            raise DomainValidationError("Reference security_id must be positive.")
        if any(source_id < 1 for source_id in self.financial_source_ids):
            raise DomainValidationError(
                "Reference financial source IDs must be positive."
            )
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise DomainValidationError(
                "Reference available_at must be timezone-aware."
            )
        object.__setattr__(self, "available_at", self.available_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class ValueScoreMeasure:
    """One disclosed raw measure and its metric-specific score, when available."""

    code: str
    value: Decimal | None
    unit: str
    score: Decimal | None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.unit.strip():
            raise DomainValidationError(
                "Value Score measure code and unit are required."
            )
        for value_name in ("value", "score"):
            value = getattr(self, value_name)
            if value is not None and not value.is_finite():
                raise DomainValidationError(f"{value_name} must be finite.")
        if self.score is not None and not 0 <= self.score <= 100:
            raise DomainValidationError("Measure scores must be in [0, 100].")
        if self.score is None and not self.reason:
            raise DomainValidationError("Unavailable measures require an explanation.")


@dataclass(frozen=True, slots=True)
class ValueScoreComponent:
    """Assessment of one weighted Value Score component."""

    code: ValueScoreComponentCode
    status: ValueScoreComponentStatus
    score: Decimal | None
    reason: str | None
    measures: tuple[ValueScoreMeasure, ...] = ()
    input_references: tuple[ValueScoreInputReference, ...] = ()
    peer_security_ids: tuple[int, ...] = ()
    original_weight: Decimal = Decimal(0)
    effective_weight: Decimal = Decimal(0)
    exclusion_reasons: tuple[str, ...] = ()
    excluded_peer_reasons: tuple[tuple[int, str], ...] = ()
    coverage: Decimal | None = None

    def __post_init__(self) -> None:
        if self.score is not None and (
            not self.score.is_finite() or not 0 <= self.score <= 100
        ):
            raise DomainValidationError("Component scores must be in [0, 100].")
        if self.original_weight < 0 or self.effective_weight < 0:
            raise DomainValidationError("Component weights must not be negative.")
        coverage = self.coverage
        if coverage is None:
            if self.status == ValueScoreComponentStatus.PARTIAL:
                # Legacy snapshots may not contain enough measures to recover it.
                pass
            else:
                coverage = (
                    Decimal(1)
                    if self.status == ValueScoreComponentStatus.AVAILABLE
                    else Decimal(0)
                )
                object.__setattr__(self, "coverage", coverage)
        if coverage is not None and (
            not coverage.is_finite() or not Decimal(0) <= coverage <= Decimal(1)
        ):
            raise DomainValidationError("Component coverage must be in [0, 1].")
        if (self.score is None) != (
            self.status
            in {
                ValueScoreComponentStatus.UNAVAILABLE,
                ValueScoreComponentStatus.INVALID_INPUT,
            }
        ):
            raise DomainValidationError("Component score and status conflict.")
        if self.score is None and not self.reason:
            raise DomainValidationError("Unavailable components require a reason.")
        if self.status == ValueScoreComponentStatus.AVAILABLE and coverage != 1:
            raise DomainValidationError("Available components require full coverage.")
        if (
            self.status == ValueScoreComponentStatus.PARTIAL
            and coverage is not None
            and not 0 < coverage < 1
        ):
            raise DomainValidationError("Partial components require partial coverage.")
        if (
            self.status
            in {
                ValueScoreComponentStatus.UNAVAILABLE,
                ValueScoreComponentStatus.INVALID_INPUT,
            }
            and coverage != 0
        ):
            raise DomainValidationError("Unavailable components have zero coverage.")
        if any(peer < 1 for peer in self.peer_security_ids):
            raise DomainValidationError("Peer security IDs must be positive.")
        if any(
            peer < 1 or not reason.strip()
            for peer, reason in self.excluded_peer_reasons
        ):
            raise DomainValidationError("Excluded peer audit entries are invalid.")


@dataclass(frozen=True, slots=True)
class ValueScore:
    """Append-only reproducible Value Score snapshot."""

    security_id: int
    company_id: int
    as_of: datetime
    score: Decimal | None
    coverage: Decimal
    status: ValueScoreStatus
    confidence: ValueScoreConfidence
    config_version: int
    config_snapshot: dict[str, object]
    components: tuple[ValueScoreComponent, ...]
    status_reason: str | None
    id: int | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.security_id < 1 or self.company_id < 1 or self.config_version < 1:
            raise DomainValidationError("Value Score identity/version is invalid.")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DomainValidationError("Value Score as_of must be timezone-aware.")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
        if self.created_at is not None:
            if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
                raise DomainValidationError("created_at must be timezone-aware.")
            object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))
        if not self.coverage.is_finite() or not 0 <= self.coverage <= 1:
            raise DomainValidationError("Value Score coverage must be in [0, 1].")
        if self.score is not None and (
            not self.score.is_finite() or not 0 <= self.score <= 100
        ):
            raise DomainValidationError("Value Score must be in [0, 100].")
        if (self.status == ValueScoreStatus.INSUFFICIENT_DATA) != (self.score is None):
            raise DomainValidationError("Value Score status and score conflict.")
        codes = [component.code for component in self.components]
        if len(codes) != len(set(codes)) or set(codes) != set(ValueScoreComponentCode):
            raise DomainValidationError(
                "Every Value Score component must be recorded once."
            )
        if any(
            reference.available_at > self.as_of
            or (
                reference.observation_date is not None
                and reference.observation_date > self.as_of.date()
            )
            for component in self.components
            for reference in component.input_references
        ):
            raise DomainValidationError(
                "Value Score provenance is after its as_of cutoff."
            )
        if sum((item.effective_weight for item in self.components), Decimal(0)) not in {
            Decimal(0),
            Decimal(1),
        }:
            raise DomainValidationError(
                "Effective component weights must total zero or one."
            )
