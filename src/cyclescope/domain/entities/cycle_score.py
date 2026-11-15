"""Immutable domain contracts for point-in-time earnings Cycle Scores."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from enum import StrEnum

from cyclescope.domain.exceptions import DomainValidationError


class CyclePhase(StrEnum):
    EARLY_RECOVERY = "EARLY_RECOVERY"
    EXPANSION = "EXPANSION"
    PEAK = "PEAK"
    CONTRACTION = "CONTRACTION"
    TROUGH = "TROUGH"
    UNKNOWN = "UNKNOWN"


class CycleScoreStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class CycleScoreConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT = "INSUFFICIENT"


class CycleScoreComponentCode(StrEnum):
    EARNINGS_MOMENTUM = "EARNINGS_MOMENTUM"
    EARNINGS_ACCELERATION = "EARNINGS_ACCELERATION"
    HISTORICAL_POSITION = "HISTORICAL_POSITION"
    TREND_CONFIRMATION = "TREND_CONFIRMATION"


class CycleScoreComponentStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


DEFAULT_CYCLE_SCORE_WEIGHTS = (
    (CycleScoreComponentCode.EARNINGS_MOMENTUM, Decimal("0.35")),
    (CycleScoreComponentCode.EARNINGS_ACCELERATION, Decimal("0.25")),
    (CycleScoreComponentCode.HISTORICAL_POSITION, Decimal("0.15")),
    (CycleScoreComponentCode.TREND_CONFIRMATION, Decimal("0.25")),
)

DEFAULT_PHASE_SCORES = (
    (CyclePhase.EARLY_RECOVERY, Decimal("70")),
    (CyclePhase.EXPANSION, Decimal("85")),
    (CyclePhase.PEAK, Decimal("35")),
    (CyclePhase.CONTRACTION, Decimal("25")),
    (CyclePhase.TROUGH, Decimal("45")),
    (CyclePhase.UNKNOWN, Decimal("50")),
)


@dataclass(frozen=True, slots=True)
class CycleScoreConfig:
    """Versioned thresholds, formulas, confidence rules, and score weights."""

    version: int = 1
    window_years: int = 7
    minimum_observations: int = 5
    high_confidence_observations: int = 7
    recent_observation_count: int = 3
    trough_confirmation_changes: int = 2
    weights: tuple[tuple[CycleScoreComponentCode, Decimal], ...] = (
        DEFAULT_CYCLE_SCORE_WEIGHTS
    )
    phase_scores: tuple[tuple[CyclePhase, Decimal], ...] = DEFAULT_PHASE_SCORES
    minimum_coverage: Decimal = Decimal("0.6")
    medium_confidence_coverage: Decimal = Decimal("0.7")
    high_confidence_coverage: Decimal = Decimal("0.85")
    momentum_deadband: Decimal = Decimal("0.02")
    momentum_full_scale: Decimal = Decimal("0.2")
    acceleration_deadband: Decimal = Decimal("0.01")
    acceleration_full_scale: Decimal = Decimal("0.1")
    low_earnings_position: Decimal = Decimal("0.25")
    high_earnings_position: Decimal = Decimal("0.75")
    minimum_trend_confirmation: Decimal = Decimal("0.6")

    def __post_init__(self) -> None:
        if self.version < 1:
            raise DomainValidationError("Cycle Score version must be positive.")
        if self.window_years not in {5, 7, 10}:
            raise DomainValidationError("Cycle Score window must be 5, 7, or 10.")
        if not 3 <= self.minimum_observations <= self.window_years:
            raise DomainValidationError(
                "Minimum observations must be between 3 and the analysis window."
            )
        if self.high_confidence_observations < self.minimum_observations:
            raise DomainValidationError(
                "High-confidence sample size cannot be below the minimum."
            )
        if not 3 <= self.recent_observation_count <= self.minimum_observations:
            raise DomainValidationError(
                "Recent observation count must be 3 through the minimum sample size."
            )
        if not 1 <= self.trough_confirmation_changes < self.recent_observation_count:
            raise DomainValidationError("Trough confirmation window is invalid.")
        weight_codes = [code for code, _ in self.weights]
        if len(weight_codes) != len(set(weight_codes)) or set(weight_codes) != set(
            CycleScoreComponentCode
        ):
            raise DomainValidationError(
                "Cycle Score weights must define each component exactly once."
            )
        if any(not weight.is_finite() or weight < 0 for _, weight in self.weights):
            raise DomainValidationError(
                "Cycle Score weights must be finite and non-negative."
            )
        if sum((weight for _, weight in self.weights), Decimal(0)) != Decimal(1):
            raise DomainValidationError("Cycle Score weights must total exactly 1.")
        phases = [phase for phase, _ in self.phase_scores]
        if len(phases) != len(set(phases)) or set(phases) != set(CyclePhase):
            raise DomainValidationError(
                "Phase scores must define each cycle phase exactly once."
            )
        if any(
            not score.is_finite() or not Decimal(0) <= score <= Decimal(100)
            for _, score in self.phase_scores
        ):
            raise DomainValidationError("Phase scores must be finite and in [0, 100].")
        for name in (
            "minimum_coverage",
            "medium_confidence_coverage",
            "high_confidence_coverage",
            "minimum_trend_confirmation",
        ):
            value = getattr(self, name)
            if not value.is_finite() or not Decimal(0) <= value <= Decimal(1):
                raise DomainValidationError(f"{name} must be in [0, 1].")
        if not (
            self.minimum_coverage
            <= self.medium_confidence_coverage
            <= self.high_confidence_coverage
        ):
            raise DomainValidationError(
                "Cycle Score coverage thresholds are unordered."
            )
        if not (
            Decimal(0) < self.momentum_deadband < self.momentum_full_scale
            and Decimal(0) < self.acceleration_deadband < self.acceleration_full_scale
        ):
            raise DomainValidationError("Trend deadbands and scales are invalid.")
        if not (
            Decimal(0)
            <= self.low_earnings_position
            < self.high_earnings_position
            <= Decimal(1)
        ):
            raise DomainValidationError("Earnings position thresholds are invalid.")

    @property
    def weight_map(self) -> dict[CycleScoreComponentCode, Decimal]:
        return dict(self.weights)

    @property
    def phase_score_map(self) -> dict[CyclePhase, Decimal]:
        return dict(self.phase_scores)

    def snapshot(self) -> dict[str, object]:
        """Return the exact JSON-compatible configuration used in a calculation."""
        return {
            "version": self.version,
            "window_years": self.window_years,
            "minimum_observations": self.minimum_observations,
            "high_confidence_observations": self.high_confidence_observations,
            "recent_observation_count": self.recent_observation_count,
            "trough_confirmation_changes": self.trough_confirmation_changes,
            "weights": {code.value: str(weight) for code, weight in self.weights},
            "phase_scores": {
                phase.value: str(score) for phase, score in self.phase_scores
            },
            "minimum_coverage": str(self.minimum_coverage),
            "medium_confidence_coverage": str(self.medium_confidence_coverage),
            "high_confidence_coverage": str(self.high_confidence_coverage),
            "momentum_deadband": str(self.momentum_deadband),
            "momentum_full_scale": str(self.momentum_full_scale),
            "acceleration_deadband": str(self.acceleration_deadband),
            "acceleration_full_scale": str(self.acceleration_full_scale),
            "low_earnings_position": str(self.low_earnings_position),
            "high_earnings_position": str(self.high_earnings_position),
            "minimum_trend_confirmation": str(self.minimum_trend_confirmation),
            "weight_redistribution": "NONE",
        }


@dataclass(frozen=True, slots=True)
class CycleScoreInputReference:
    """PIT provenance for an annual statement line used by the score."""

    record_id: int
    statement_id: int
    normalized_earnings_result_id: int
    source_id: int
    revision_number: int
    fiscal_year: int
    fiscal_period: str
    item_code: str
    period_end: date
    available_at: datetime
    period_start: date | None = None
    publication_date: date | None = None
    publication_datetime: datetime | None = None

    def __post_init__(self) -> None:
        if (
            min(
                self.record_id,
                self.statement_id,
                self.normalized_earnings_result_id,
                self.source_id,
                self.revision_number,
                self.fiscal_year,
            )
            < 1
        ):
            raise DomainValidationError("Cycle Score reference IDs must be positive.")
        if not self.item_code.strip() or not self.fiscal_period.strip():
            raise DomainValidationError(
                "Cycle Score reference period/item is required."
            )
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise DomainValidationError("Cycle Score available_at must be aware.")
        object.__setattr__(self, "available_at", self.available_at.astimezone(UTC))
        if self.period_start is not None and self.period_start > self.period_end:
            raise DomainValidationError("Cycle Score reference period is invalid.")
        if self.publication_datetime is not None:
            if (
                self.publication_datetime.tzinfo is None
                or self.publication_datetime.utcoffset() is None
            ):
                raise DomainValidationError(
                    "Cycle Score publication_datetime must be aware."
                )
            publication = self.publication_datetime.astimezone(UTC)
            if publication > self.available_at:
                raise DomainValidationError(
                    "Cycle Score availability cannot precede publication."
                )
            object.__setattr__(self, "publication_datetime", publication)


@dataclass(frozen=True, slots=True)
class CycleScoreObservation:
    """One observed annual operating-profit value; gaps remain absent."""

    fiscal_year: int
    value: Decimal
    currency: str
    source_id: int
    calculation_version: int
    period_start: date
    period_end: date
    references: tuple[CycleScoreInputReference, ...]

    def __post_init__(self) -> None:
        if self.fiscal_year < 1 or self.source_id < 1 or self.calculation_version < 1:
            raise DomainValidationError("Cycle Score observation identity is invalid.")
        if not self.value.is_finite():
            raise DomainValidationError("Cycle Score earnings must be finite.")
        if self.period_start > self.period_end:
            raise DomainValidationError("Cycle Score observation period is invalid.")
        if len(self.currency) != 3 or not self.currency.isupper():
            raise DomainValidationError("Cycle Score currency is invalid.")
        if not self.references:
            raise DomainValidationError("Cycle Score observations need provenance.")


@dataclass(frozen=True, slots=True)
class CycleScoreComponent:
    code: CycleScoreComponentCode
    status: CycleScoreComponentStatus
    score: Decimal | None
    value: Decimal | None
    coverage: Decimal | None
    reason: str | None = None

    def __post_init__(self) -> None:
        for name in ("score", "value", "coverage"):
            value = getattr(self, name)
            if value is not None and not value.is_finite():
                raise DomainValidationError(f"Cycle Score {name} must be finite.")
        if self.score is not None and not Decimal(0) <= self.score <= Decimal(100):
            raise DomainValidationError("Component score must be in [0, 100].")
        if self.coverage is not None and not Decimal(0) <= self.coverage <= Decimal(1):
            raise DomainValidationError("Component coverage must be in [0, 1].")
        if (self.status == CycleScoreComponentStatus.AVAILABLE) != (
            self.score is not None
        ):
            raise DomainValidationError("Component status conflicts with its score.")
        if self.score is None and not self.reason:
            raise DomainValidationError("Unavailable components need a reason.")


@dataclass(frozen=True, slots=True)
class CycleScore:
    company_id: int
    security_id: int | None
    as_of: datetime
    score: Decimal | None
    status: CycleScoreStatus
    phase: CyclePhase
    phase_reason: str
    confidence: CycleScoreConfidence
    coverage: Decimal | None
    currency: str | None
    source_id: int | None
    normalized_earnings_result_id: int
    calculation_version: int
    config_snapshot: dict[str, object]
    components: tuple[CycleScoreComponent, ...]
    input_references: tuple[CycleScoreInputReference, ...]
    status_reason: str | None = None
    created_at: datetime | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if self.company_id < 1 or (
            self.security_id is not None and self.security_id < 1
        ):
            raise DomainValidationError("Cycle Score identity is invalid.")
        if self.normalized_earnings_result_id < 1 or self.calculation_version < 1:
            raise DomainValidationError("Cycle Score provenance/version is invalid.")
        if self.source_id is not None and self.source_id < 1:
            raise DomainValidationError("Cycle Score source ID is invalid.")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DomainValidationError("Cycle Score as_of must be timezone-aware.")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
        if self.created_at is not None:
            if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
                raise DomainValidationError("Cycle Score created_at must be aware.")
            object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))
        if self.currency is not None and (
            len(self.currency) != 3 or not self.currency.isupper()
        ):
            raise DomainValidationError("Cycle Score currency is invalid.")
        if self.coverage is not None and (
            not self.coverage.is_finite()
            or not Decimal(0) <= self.coverage <= Decimal(1)
        ):
            raise DomainValidationError("Cycle Score coverage must be in [0, 1].")
        if self.score is not None and (
            not self.score.is_finite() or not Decimal(0) <= self.score <= Decimal(100)
        ):
            raise DomainValidationError("Cycle Score must be in [0, 100].")
        if (self.status == CycleScoreStatus.INSUFFICIENT_DATA) != (self.score is None):
            raise DomainValidationError("Cycle Score status and score conflict.")
        component_codes = [component.code for component in self.components]
        if len(component_codes) != len(set(component_codes)) or set(
            component_codes
        ) != set(CycleScoreComponentCode):
            raise DomainValidationError("Every Cycle Score component must be recorded.")
        if any(
            reference.available_at > self.as_of for reference in self.input_references
        ):
            raise DomainValidationError("A Cycle Score reference is after as_of.")


def clamp(value: Decimal) -> Decimal:
    return min(Decimal(1), max(Decimal(-1), value))


def quantize_score(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0000001"), rounding=ROUND_HALF_EVEN)
