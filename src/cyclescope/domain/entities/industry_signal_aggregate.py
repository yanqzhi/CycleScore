"""Append-only provider-neutral industry signal aggregate snapshots."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from cyclescope.domain.entities.industry_signal import (
    IndustrySignalTemporalKind,
    IndustrySignalType,
    IndustrySignalUnit,
)
from cyclescope.domain.exceptions import DomainValidationError


class AggregationPolicyCode(StrEnum):
    """Explicit v1 policy identifiers; policy selection is never inferred."""

    FLOW_SUM = "FLOW_SUM"
    INVENTORY_SUM = "INVENTORY_SUM"
    CAPACITY_SUM = "CAPACITY_SUM"
    CAPACITY_WEIGHTED_UTILIZATION = "CAPACITY_WEIGHTED_UTILIZATION"


class AggregateStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class AggregationOperation(StrEnum):
    SUM = "SUM"
    CAPACITY_WEIGHTED_AVERAGE = "CAPACITY_WEIGHTED_AVERAGE"


class AggregateInputRole(StrEnum):
    MEASURE = "MEASURE"
    CAPACITY_WEIGHT = "CAPACITY_WEIGHT"


@dataclass(frozen=True, slots=True)
class IndustrySignalAggregationPolicy:
    policy_code: AggregationPolicyCode
    version: int
    operation: AggregationOperation
    signal_type: IndustrySignalType
    minimum_coverage: Decimal = Decimal("0.80")

    def __post_init__(self) -> None:
        if self.version < 1:
            raise DomainValidationError("Policy version must be positive.")
        exponent = self.minimum_coverage.as_tuple().exponent
        if not isinstance(exponent, int) or max(-exponent, 0) > 7:
            raise DomainValidationError("minimum_coverage supports at most 7 decimals.")
        if not self.minimum_coverage.is_finite() or not Decimal(
            0
        ) <= self.minimum_coverage <= Decimal(1):
            raise DomainValidationError("minimum_coverage must be within [0, 1].")


@dataclass(frozen=True, slots=True)
class IndustrySignalAggregateContributor:
    observation_id: int
    source_id: int
    revision_number: int
    region_code: str
    observation_date: date | None
    period_start: date | None
    period_end: date | None
    publication_date: date
    publication_datetime: datetime | None
    available_at: datetime
    collected_at: datetime
    source_reference: str | None
    role: AggregateInputRole
    value: Decimal | None
    unit_code: IndustrySignalUnit
    currency_code: str | None
    classification_version_id: int | None
    classification_mapping_id: int | None
    included: bool
    calculation_weight: Decimal | None = None
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        if self.observation_id < 1 or self.source_id < 1 or self.revision_number < 1:
            raise DomainValidationError("Contributor references must be positive.")
        if self.unit_code is IndustrySignalUnit.CURRENCY:
            _validate_currency(self.currency_code)
        elif self.currency_code is not None:
            raise DomainValidationError("currency_code requires CURRENCY unit.")
        for name in ("publication_datetime", "available_at", "collected_at"):
            value = getattr(self, name)
            if value is not None:
                if value.tzinfo is None or value.utcoffset() is None:
                    raise DomainValidationError(f"{name} must be timezone-aware.")
                object.__setattr__(self, name, value.astimezone(UTC))
        if (self.classification_version_id is None) != (
            self.classification_mapping_id is None
        ):
            raise DomainValidationError(
                "Classification version and mapping references must be paired."
            )
        if self.included and self.value is None:
            raise DomainValidationError("An included contributor must have a value.")
        if not self.included and not (self.exclusion_reason or "").strip():
            raise DomainValidationError(
                "An excluded contributor requires an exclusion reason."
            )
        if self.calculation_weight is not None and (
            not self.calculation_weight.is_finite() or self.calculation_weight < 0
        ):
            raise DomainValidationError("Contributor weight must be non-negative.")
        if (
            self.included
            and self.calculation_weight is not None
            and self.calculation_weight <= 0
        ):
            raise DomainValidationError(
                "Included calculation weights must be positive."
            )


@dataclass(frozen=True, slots=True)
class IndustrySignalAggregateSnapshot:
    industry_id: int
    sub_industry_id: int | None
    signal_type: IndustrySignalType
    temporal_kind: IndustrySignalTemporalKind
    aggregate_region_code: str
    source_id: int | None
    unit_code: IndustrySignalUnit
    currency_code: str | None
    observation_date: date | None
    period_start: date | None
    period_end: date | None
    as_of: datetime
    calculated_at: datetime
    policy_code: AggregationPolicyCode
    policy_version: int
    calculation_version: int
    operation: AggregationOperation
    minimum_coverage: Decimal
    value: Decimal | None
    status: AggregateStatus
    expected_contributor_count: int | None
    actual_contributor_count: int
    coverage_ratio: Decimal | None
    confidence: Decimal | None
    missing_reasons: tuple[str, ...]
    validation_warnings: tuple[str, ...]
    contributors: tuple[IndustrySignalAggregateContributor, ...]
    id: int | None = None

    def __post_init__(self) -> None:
        for name in ("as_of", "calculated_at"):
            value = getattr(self, name)
            if value.tzinfo is None or value.utcoffset() is None:
                raise DomainValidationError(f"{name} must be timezone-aware.")
            object.__setattr__(self, name, value.astimezone(UTC))
        if self.industry_id < 1 or (
            self.sub_industry_id is not None and self.sub_industry_id < 1
        ):
            raise DomainValidationError("Industry references must be positive.")
        if self.source_id is not None and self.source_id < 1:
            raise DomainValidationError("source_id must be positive when supplied.")
        if self.signal_type in {
            IndustrySignalType.CAPACITY_ADDITION,
            IndustrySignalType.CAPACITY_CLOSURE_ANNOUNCED,
            IndustrySignalType.CAPACITY_CLOSURE_COMPLETED,
        }:
            raise DomainValidationError("Event signals are not aggregatable in v1.")
        expected_period = self.signal_type in {
            IndustrySignalType.PRODUCTION,
            IndustrySignalType.SHIPMENTS,
            IndustrySignalType.SALES,
            IndustrySignalType.ORDERS,
        }
        if (self.temporal_kind is IndustrySignalTemporalKind.PERIOD) != expected_period:
            raise DomainValidationError(
                "Temporal kind is incompatible with signal type."
            )
        expected_operation = (
            AggregationOperation.CAPACITY_WEIGHTED_AVERAGE
            if self.signal_type is IndustrySignalType.CAPACITY_UTILIZATION
            else AggregationOperation.SUM
        )
        if self.operation is not expected_operation:
            raise DomainValidationError(
                "Aggregation operation is incompatible with signal type."
            )
        expected_policy = {
            IndustrySignalType.INVENTORY: AggregationPolicyCode.INVENTORY_SUM,
            IndustrySignalType.PRODUCTION: AggregationPolicyCode.FLOW_SUM,
            IndustrySignalType.SHIPMENTS: AggregationPolicyCode.FLOW_SUM,
            IndustrySignalType.SALES: AggregationPolicyCode.FLOW_SUM,
            IndustrySignalType.ORDERS: AggregationPolicyCode.FLOW_SUM,
            IndustrySignalType.CAPACITY: AggregationPolicyCode.CAPACITY_SUM,
            IndustrySignalType.CAPACITY_UTILIZATION: (
                AggregationPolicyCode.CAPACITY_WEIGHTED_UTILIZATION
            ),
        }[self.signal_type]
        if self.policy_code is not expected_policy:
            raise DomainValidationError(
                "Aggregation policy does not match signal type."
            )
        if self.unit_code is IndustrySignalUnit.CURRENCY:
            _validate_currency(self.currency_code)
        elif self.currency_code is not None:
            raise DomainValidationError("currency_code requires CURRENCY unit.")
        exponent = self.minimum_coverage.as_tuple().exponent
        if not isinstance(exponent, int) or max(-exponent, 0) > 7:
            raise DomainValidationError("minimum_coverage supports at most 7 decimals.")
        if not self.aggregate_region_code.strip():
            raise DomainValidationError("aggregate_region_code is required.")
        if self.policy_version < 1 or self.calculation_version < 1:
            raise DomainValidationError(
                "Policy and calculation versions must be positive."
            )
        if self.expected_contributor_count is not None and (
            self.expected_contributor_count < 1
        ):
            raise DomainValidationError(
                "expected_contributor_count must be positive when supplied."
            )
        if self.actual_contributor_count < 0:
            raise DomainValidationError("actual_contributor_count cannot be negative.")
        for name, value in (
            ("coverage_ratio", self.coverage_ratio),
            ("confidence", self.confidence),
            ("minimum_coverage", self.minimum_coverage),
        ):
            if value is not None and (
                not value.is_finite() or not Decimal(0) <= value <= Decimal(1)
            ):
                raise DomainValidationError(f"{name} must be within [0, 1].")
        if self.status is AggregateStatus.INSUFFICIENT_DATA and self.value is not None:
            raise DomainValidationError(
                "Insufficient-data snapshots cannot expose an aggregate value."
            )
        if self.status is not AggregateStatus.INSUFFICIENT_DATA and self.value is None:
            raise DomainValidationError(
                "Available snapshots require an aggregate value."
            )
        if self.status is AggregateStatus.AVAILABLE and self.coverage_ratio != Decimal(
            1
        ):
            raise DomainValidationError("AVAILABLE requires complete known coverage.")
        if self.status is AggregateStatus.PARTIAL and self.coverage_ratio == Decimal(1):
            raise DomainValidationError("PARTIAL cannot have complete coverage.")
        if self.value is not None and not self.value.is_finite():
            raise DomainValidationError("Aggregate value must be finite.")
        if self.temporal_kind is IndustrySignalTemporalKind.PERIOD:
            if (
                self.observation_date is not None
                or self.period_start is None
                or self.period_end is None
                or self.period_start > self.period_end
            ):
                raise DomainValidationError("Aggregate period boundaries are invalid.")
        elif (
            self.observation_date is None
            or self.period_start is not None
            or self.period_end is not None
        ):
            raise DomainValidationError("Aggregate observation date shape is invalid.")


def _validate_currency(currency_code: str | None) -> None:
    if (
        currency_code is None
        or len(currency_code) != 3
        or not currency_code.isascii()
        or not currency_code.isalpha()
        or not currency_code.isupper()
    ):
        raise DomainValidationError("currency_code must be three uppercase letters.")
