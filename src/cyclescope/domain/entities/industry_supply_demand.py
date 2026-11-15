"""Immutable Industry Supply & Demand v1 Domain snapshots."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from cyclescope.domain.entities.industry_inventory import (
    IndustryInventoryClassification,
    IndustryInventoryTrend,
)
from cyclescope.domain.entities.industry_signal import IndustrySignalUnit
from cyclescope.domain.exceptions import DomainValidationError


class IndustrySupplyDemandPhase(StrEnum):
    DEMAND_RECOVERY = "DEMAND_RECOVERY"
    EXPANSION = "EXPANSION"
    BALANCED = "BALANCED"
    OVERSUPPLY = "OVERSUPPLY"
    DEMAND_SLOWDOWN = "DEMAND_SLOWDOWN"
    UNDERSUPPLY = "UNDERSUPPLY"
    UNKNOWN = "UNKNOWN"


class IndustrySupplyDemandStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True, slots=True)
class IndustrySupplyDemandConfig:
    version: int
    minimum_coverage: Decimal
    flow_gap_tolerance: Decimal
    strong_demand_growth: Decimal
    negative_demand_growth: Decimal
    inventory_accumulation_yoy: Decimal
    inventory_drawdown_yoy: Decimal
    minimum_evidence_coverage: Decimal

    def __post_init__(self) -> None:
        values = (
            self.minimum_coverage,
            self.flow_gap_tolerance,
            self.strong_demand_growth,
            self.negative_demand_growth,
            self.inventory_accumulation_yoy,
            self.inventory_drawdown_yoy,
            self.minimum_evidence_coverage,
        )
        if self.version < 1:
            raise DomainValidationError("Configuration version must be positive.")
        if any(not value.is_finite() for value in values):
            raise DomainValidationError("Configuration values must be finite.")
        if not Decimal(0) <= self.minimum_coverage <= Decimal(1):
            raise DomainValidationError("minimum_coverage must be within [0, 1].")
        if not Decimal(0) <= self.flow_gap_tolerance <= Decimal(1):
            raise DomainValidationError("flow_gap_tolerance must be within [0, 1].")
        if not Decimal(0) <= self.minimum_evidence_coverage <= Decimal(1):
            raise DomainValidationError(
                "minimum_evidence_coverage must be within [0, 1]."
            )
        if self.strong_demand_growth < 0:
            raise DomainValidationError("strong_demand_growth must be non-negative.")
        if self.negative_demand_growth > 0:
            raise DomainValidationError("negative_demand_growth must be non-positive.")
        if self.inventory_accumulation_yoy < 0:
            raise DomainValidationError(
                "inventory_accumulation_yoy must be non-negative."
            )
        if self.inventory_drawdown_yoy > 0:
            raise DomainValidationError("inventory_drawdown_yoy must be non-positive.")
        if self.negative_demand_growth >= self.strong_demand_growth:
            raise DomainValidationError(
                "Negative demand threshold must be below strong demand growth."
            )
        if self.inventory_drawdown_yoy >= self.inventory_accumulation_yoy:
            raise DomainValidationError(
                "Inventory drawdown threshold must be below accumulation threshold."
            )


@dataclass(frozen=True, slots=True)
class IndustrySupplyDemandInputReference:
    role: str
    aggregate_id: int | None
    inventory_snapshot_id: int | None
    period_start: date | None
    period_end: date | None
    source_id: int | None
    unit_code: str | None
    currency_code: str | None
    available_at: datetime
    contributing_regions: tuple[tuple[int, str], ...]
    coverage: Decimal | None
    policy_code: str | None = None
    policy_version: int | None = None
    calculation_version: int | None = None
    classification_references: tuple[tuple[int | None, int | None], ...] = ()
    contributor_revisions: tuple[tuple[int, int, int], ...] = ()
    included: bool = True
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.role.strip():
            raise DomainValidationError("Input reference role is required.")
        if (self.aggregate_id is None) == (self.inventory_snapshot_id is None):
            raise DomainValidationError(
                "Input reference must identify exactly one source snapshot."
            )
        if self.aggregate_id is not None and self.aggregate_id < 1:
            raise DomainValidationError("aggregate_id must be positive.")
        if self.inventory_snapshot_id is not None and self.inventory_snapshot_id < 1:
            raise DomainValidationError("inventory_snapshot_id must be positive.")
        if self.source_id is not None and self.source_id < 1:
            raise DomainValidationError("source_id must be positive when supplied.")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise DomainValidationError("Input availability must be timezone-aware.")
        object.__setattr__(self, "available_at", self.available_at.astimezone(UTC))
        if self.contributing_regions != tuple(sorted(set(self.contributing_regions))):
            raise DomainValidationError(
                "Input contributor regions must be unique and ordered."
            )
        if self.coverage is not None and (
            not self.coverage.is_finite()
            or not Decimal(0) <= self.coverage <= Decimal(1)
        ):
            raise DomainValidationError("Input coverage must be within [0, 1].")
        if self.unit_code is not None and (
            (self.unit_code == IndustrySignalUnit.CURRENCY.value)
            != (self.currency_code is not None)
        ):
            raise DomainValidationError("Input currency must match its unit.")
        if self.unit_code is None and self.currency_code is not None:
            raise DomainValidationError("Input currency requires a unit.")
        if self.included and self.exclusion_reason is not None:
            raise DomainValidationError(
                "Included inputs cannot have an exclusion reason."
            )
        if not self.included and not (self.exclusion_reason or "").strip():
            raise DomainValidationError("Excluded inputs require an explicit reason.")
        if any(
            min(observation_id, source_id, revision) < 1
            for observation_id, source_id, revision in self.contributor_revisions
        ):
            raise DomainValidationError("Contributor revision reference is invalid.")


@dataclass(frozen=True, slots=True)
class IndustrySupplyDemandSnapshot:
    industry_id: int
    sub_industry_id: int | None
    aggregate_region_id: int | None
    aggregate_region_code: str
    requested_scope: tuple[tuple[int, str], ...]
    contributing_regions: tuple[tuple[int, str], ...]
    source_id: int | None
    unit_code: str | None
    currency_code: str | None
    period_start: date | None
    period_end: date | None
    observation_date: date | None
    as_of: datetime
    calculated_at: datetime
    phase: IndustrySupplyDemandPhase
    status: IndustrySupplyDemandStatus
    production_value: Decimal | None
    shipments_value: Decimal | None
    flow_gap: Decimal | None
    flow_gap_ratio: Decimal | None
    shipment_growth_yoy: Decimal | None
    inventory_snapshot_id: int | None
    inventory_classification: IndustryInventoryClassification | None
    inventory_trend: IndustryInventoryTrend | None
    inventory_yoy_growth: Decimal | None
    inventory_growth_acceleration: Decimal | None
    inventory_coverage: Decimal | None
    inventory_confidence: Decimal | None
    coverage: Decimal | None
    evidence_coverage: Decimal
    confidence: Decimal | None
    config: IndustrySupplyDemandConfig
    input_references: tuple[IndustrySupplyDemandInputReference, ...]
    unavailable_reasons: tuple[str, ...]
    validation_warnings: tuple[str, ...] = ()
    id: int | None = None

    def __post_init__(self) -> None:
        for name in ("as_of", "calculated_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise DomainValidationError(f"{name} must be timezone-aware.")
            object.__setattr__(self, name, value.astimezone(UTC))
        if self.industry_id < 1 or not self.aggregate_region_code.strip():
            raise DomainValidationError("Industry supply-demand identity is invalid.")
        if self.sub_industry_id is not None and self.sub_industry_id < 1:
            raise DomainValidationError("sub_industry_id must be positive.")
        if self.aggregate_region_id is not None and self.aggregate_region_id < 1:
            raise DomainValidationError("aggregate_region_id must be positive.")
        if not self.requested_scope or self.requested_scope != tuple(
            sorted(set(self.requested_scope))
        ):
            raise DomainValidationError(
                "Requested scope must be non-empty, unique, and ordered."
            )
        if self.contributing_regions != tuple(sorted(set(self.contributing_regions))):
            raise DomainValidationError(
                "Contributing regions must be unique and ordered."
            )
        if not set(self.contributing_regions).issubset(set(self.requested_scope)):
            raise DomainValidationError(
                "Contributing regions must belong to requested scope."
            )
        if self.source_id is not None and self.source_id < 1:
            raise DomainValidationError("source_id must be positive when supplied.")
        if self.unit_code is not None and (
            (self.unit_code == IndustrySignalUnit.CURRENCY.value)
            != (self.currency_code is not None)
        ):
            raise DomainValidationError("Snapshot currency must match its unit.")
        if self.unit_code is None and self.currency_code is not None:
            raise DomainValidationError("Snapshot currency requires a unit.")
        if self.period_start is not None and self.period_end is not None:
            if self.period_start > self.period_end:
                raise DomainValidationError("Snapshot period boundaries are invalid.")
        if self.observation_date != self.period_end:
            raise DomainValidationError("Observation date must equal period end.")
        if self.period_end is not None and self.period_end > self.as_of.date():
            raise DomainValidationError("Period end must not exceed as_of.")
        for field_name in (
            "production_value",
            "shipments_value",
            "flow_gap",
            "flow_gap_ratio",
            "shipment_growth_yoy",
            "inventory_yoy_growth",
            "inventory_growth_acceleration",
        ):
            value = getattr(self, field_name)
            if value is not None and not value.is_finite():
                raise DomainValidationError(f"{field_name} must be finite.")
        for field_name in (
            "coverage",
            "evidence_coverage",
            "inventory_coverage",
            "inventory_confidence",
        ):
            value = getattr(self, field_name)
            if value is not None and (
                not value.is_finite() or not Decimal(0) <= value <= Decimal(1)
            ):
                raise DomainValidationError(f"{field_name} must be within [0, 1].")
        if self.confidence is not None:
            raise DomainValidationError("Confidence is unknown in v1 and must be null.")
        if self.inventory_snapshot_id is None and any(
            value is not None
            for value in (
                self.inventory_classification,
                self.inventory_trend,
                self.inventory_yoy_growth,
                self.inventory_growth_acceleration,
            )
        ):
            raise DomainValidationError(
                "Inventory context requires an inventory snapshot reference."
            )
        if self.status is IndustrySupplyDemandStatus.INSUFFICIENT_DATA and (
            self.phase is not IndustrySupplyDemandPhase.UNKNOWN
        ):
            raise DomainValidationError("Insufficient data must have UNKNOWN phase.")
        if self.status is IndustrySupplyDemandStatus.AVAILABLE and (
            self.coverage != Decimal(1)
            or self.evidence_coverage != Decimal(1)
            or self.flow_gap is None
            or self.flow_gap_ratio is None
            or self.shipment_growth_yoy is None
            or self.inventory_snapshot_id is None
        ):
            raise DomainValidationError("AVAILABLE requires all v1 evidence groups.")
        if any(
            reference.included
            and (
                reference.available_at > self.as_of
                or (
                    reference.period_end is not None
                    and reference.period_end > self.as_of.date()
                )
                or (
                    self.source_id is not None and reference.source_id != self.source_id
                )
            )
            for reference in self.input_references
        ):
            raise DomainValidationError(
                "Input reference violates source or PIT policy."
            )
