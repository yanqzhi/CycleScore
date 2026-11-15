"""Immutable, provider-neutral industry inventory cycle snapshots."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from cyclescope.domain.entities.industry_signal import IndustrySignalUnit
from cyclescope.domain.exceptions import DomainValidationError


class IndustryInventoryClassification(StrEnum):
    ACCUMULATION = "ACCUMULATION"
    RAPID_ACCUMULATION = "RAPID_ACCUMULATION"
    DECELERATING = "DECELERATING"
    DRAWDOWN = "DRAWDOWN"
    NORMALIZATION = "NORMALIZATION"
    UNKNOWN = "UNKNOWN"


class IndustryInventoryStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class IndustryInventoryTrend(StrEnum):
    INCREASING = "INCREASING"
    DECREASING = "DECREASING"
    STABLE = "STABLE"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class IndustryInventoryConfig:
    """Versioned heuristic thresholds; callers can supply calibrated policy."""

    version: int
    accumulation_yoy: Decimal
    rapid_accumulation_yoy: Decimal
    normalization_prior_yoy: Decimal
    normalization_growth_ceiling: Decimal
    stable_growth_tolerance: Decimal
    gap_ratio_tolerance: Decimal
    minimum_coverage: Decimal
    expected_observation_interval_months: int | None = None

    def __post_init__(self) -> None:
        if self.version < 1:
            raise DomainValidationError("Configuration version must be positive.")
        values = (
            self.accumulation_yoy,
            self.rapid_accumulation_yoy,
            self.normalization_prior_yoy,
            self.normalization_growth_ceiling,
            self.stable_growth_tolerance,
            self.gap_ratio_tolerance,
            self.minimum_coverage,
        )
        if any(not value.is_finite() for value in values):
            raise DomainValidationError("Configuration values must be finite.")
        if not Decimal(0) <= self.minimum_coverage <= Decimal(1):
            raise DomainValidationError("minimum_coverage must be within [0, 1].")
        if self.accumulation_yoy < 0:
            raise DomainValidationError("accumulation_yoy must be non-negative.")
        if self.rapid_accumulation_yoy <= self.accumulation_yoy:
            raise DomainValidationError("Rapid threshold must exceed accumulation.")
        if (
            self.normalization_prior_yoy >= 0
            or self.normalization_growth_ceiling < 0
            or self.normalization_prior_yoy >= self.normalization_growth_ceiling
            or self.normalization_growth_ceiling > self.accumulation_yoy
        ):
            raise DomainValidationError(
                "Normalization thresholds must satisfy prior < 0 <= ceiling "
                "<= accumulation threshold."
            )
        if self.stable_growth_tolerance < 0 or self.gap_ratio_tolerance < 0:
            raise DomainValidationError("Tolerances cannot be negative.")
        if self.gap_ratio_tolerance > 1:
            raise DomainValidationError("gap_ratio_tolerance cannot exceed 1.")
        if self.expected_observation_interval_months is not None and (
            self.expected_observation_interval_months not in {1, 3, 6, 12}
        ):
            raise DomainValidationError(
                "Expected observation interval must be 1, 3, 6, or 12 months."
            )


@dataclass(frozen=True, slots=True)
class IndustryInventoryInputReference:
    aggregate_id: int
    role: str
    observation_date: date | None
    period_start: date | None
    period_end: date | None
    source_id: int | None
    available_at: datetime
    contributor_revisions: tuple[tuple[int, int, int], ...]
    contributing_regions: tuple[tuple[int, str], ...]
    coverage: Decimal | None
    included: bool = True
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        if self.aggregate_id < 1 or not self.role.strip():
            raise DomainValidationError("Input reference is invalid.")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise DomainValidationError("Input availability must be timezone-aware.")
        object.__setattr__(self, "available_at", self.available_at.astimezone(UTC))
        if any(
            observation_id < 1 or source_id < 1 or revision < 1
            for observation_id, source_id, revision in self.contributor_revisions
        ):
            raise DomainValidationError(
                "Contributor revision references must be positive."
            )
        if self.contributing_regions != tuple(sorted(set(self.contributing_regions))):
            raise DomainValidationError(
                "Input contributing regions must be unique and ordered."
            )
        if self.coverage is not None and (
            not self.coverage.is_finite()
            or not Decimal(0) <= self.coverage <= Decimal(1)
        ):
            raise DomainValidationError("Input coverage must be within [0, 1].")
        if self.included and self.exclusion_reason is not None:
            raise DomainValidationError(
                "Included inputs cannot have an exclusion reason."
            )
        if not self.included and not (self.exclusion_reason or "").strip():
            raise DomainValidationError("Excluded inputs require an explicit reason.")


@dataclass(frozen=True, slots=True)
class IndustryInventorySnapshot:
    industry_id: int
    sub_industry_id: int | None
    aggregate_region_code: str
    source_id: int | None
    unit_code: str
    currency_code: str | None
    observation_date: date
    as_of: datetime
    calculated_at: datetime
    classification: IndustryInventoryClassification
    trend: IndustryInventoryTrend
    status: IndustryInventoryStatus
    inventory_value: Decimal | None
    prior_inventory_value: Decimal | None
    absolute_change: Decimal | None
    yoy_growth: Decimal | None
    prior_yoy_growth: Decimal | None
    growth_acceleration: Decimal | None
    production_value: Decimal | None
    shipments_value: Decimal | None
    production_shipment_gap: Decimal | None
    coverage: Decimal | None
    confidence: Decimal | None
    config: IndustryInventoryConfig
    requested_scope: tuple[tuple[int, str], ...]
    contributing_regions: tuple[tuple[int, str], ...]
    input_references: tuple[IndustryInventoryInputReference, ...]
    unavailable_reasons: tuple[str, ...]
    id: int | None = None

    def __post_init__(self) -> None:
        for key in ("as_of", "calculated_at"):
            value = getattr(self, key)
            if value.tzinfo is None or value.utcoffset() is None:
                raise DomainValidationError(f"{key} must be timezone-aware.")
            object.__setattr__(self, key, value.astimezone(UTC))
        if self.industry_id < 1 or not self.aggregate_region_code.strip():
            raise DomainValidationError("Industry inventory identity is invalid.")
        if self.sub_industry_id is not None and self.sub_industry_id < 1:
            raise DomainValidationError("sub_industry_id must be positive.")
        if self.source_id is not None and self.source_id < 1:
            raise DomainValidationError("source_id must be positive when supplied.")
        try:
            unit = IndustrySignalUnit(self.unit_code)
        except ValueError as exc:
            raise DomainValidationError("Inventory unit is invalid.") from exc
        if (unit is IndustrySignalUnit.CURRENCY) != (self.currency_code is not None):
            raise DomainValidationError("Currency must match the inventory unit.")
        if self.currency_code is not None and (
            len(self.currency_code) != 3
            or not self.currency_code.isascii()
            or not self.currency_code.isalpha()
            or not self.currency_code.isupper()
        ):
            raise DomainValidationError(
                "currency_code must be three uppercase letters."
            )
        if self.observation_date > self.as_of.date():
            raise DomainValidationError("Observation date must not exceed as_of.")
        for name in (
            "inventory_value",
            "prior_inventory_value",
            "absolute_change",
            "yoy_growth",
            "prior_yoy_growth",
            "growth_acceleration",
            "production_value",
            "shipments_value",
            "production_shipment_gap",
        ):
            value = getattr(self, name)
            if value is not None and not value.is_finite():
                raise DomainValidationError(f"{name} must be finite.")
        if not self.requested_scope or len(set(self.requested_scope)) != len(
            self.requested_scope
        ):
            raise DomainValidationError("Requested scope must be non-empty and unique.")
        if self.requested_scope != tuple(sorted(self.requested_scope)):
            raise DomainValidationError(
                "Requested scope must be deterministically ordered."
            )
        if self.contributing_regions != tuple(sorted(self.contributing_regions)):
            raise DomainValidationError(
                "Contributing regions must be deterministically ordered."
            )
        if not set(self.contributing_regions).issubset(set(self.requested_scope)):
            raise DomainValidationError(
                "Contributing regions must belong to the requested scope."
            )
        for name in ("coverage", "confidence"):
            value = getattr(self, name)
            if value is not None and (
                not value.is_finite() or not Decimal(0) <= value <= Decimal(1)
            ):
                raise DomainValidationError(f"{name} must be finite and within [0, 1].")
        if self.status is IndustryInventoryStatus.INSUFFICIENT_DATA and (
            self.classification is not IndustryInventoryClassification.UNKNOWN
        ):
            raise DomainValidationError("Insufficient data must classify as UNKNOWN.")
        if (
            self.status is IndustryInventoryStatus.INSUFFICIENT_DATA
            and self.confidence is not None
        ):
            raise DomainValidationError("Insufficient data cannot have confidence.")
        if self.status is IndustryInventoryStatus.AVAILABLE and (
            self.coverage != Decimal(1)
            or self.confidence is None
            or self.inventory_value is None
            or self.yoy_growth is None
            or self.absolute_change is None
        ):
            raise DomainValidationError("AVAILABLE requires complete known coverage.")
        if (
            self.absolute_change is None
            and self.trend is not IndustryInventoryTrend.UNKNOWN
        ):
            raise DomainValidationError(
                "Missing absolute change requires UNKNOWN trend."
            )
        if any(
            ref.available_at > self.as_of
            or (ref.included and ref.source_id != self.source_id)
            or (
                ref.observation_date is not None
                and ref.observation_date > self.as_of.date()
            )
            or (ref.period_end is not None and ref.period_end > self.as_of.date())
            for ref in self.input_references
        ):
            raise DomainValidationError(
                "Input reference violates source or PIT policy."
            )
