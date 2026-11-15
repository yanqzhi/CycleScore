"""Immutable inputs and outputs for company-level annual inventory analysis."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from cyclescope.domain.exceptions import DomainValidationError


class InventoryTrend(StrEnum):
    INCREASING = "INCREASING"
    DECREASING = "DECREASING"
    STABLE = "STABLE"
    VOLATILE = "VOLATILE"
    UNKNOWN = "UNKNOWN"


class InventoryStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    UNAVAILABLE = "UNAVAILABLE"


class InventoryConfidence(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True, slots=True)
class InventoryConfig:
    version: int = 1
    days_per_year: int = 365
    stable_growth_threshold: Decimal = Decimal("0.05")
    minimum_trend_observations: int = 3

    def __post_init__(self) -> None:
        if self.version < 1 or self.days_per_year != 365:
            raise DomainValidationError("Inventory version or annual basis is invalid.")
        if not self.stable_growth_threshold.is_finite() or not (
            Decimal(0) <= self.stable_growth_threshold < Decimal(1)
        ):
            raise DomainValidationError("Stable growth threshold must be in [0, 1).")
        if self.minimum_trend_observations < 3:
            raise DomainValidationError(
                "At least three trend observations are required."
            )

    def snapshot(self) -> dict[str, object]:
        return {
            "version": self.version,
            "days_per_year": self.days_per_year,
            "stable_growth_threshold": str(self.stable_growth_threshold),
            "minimum_trend_observations": self.minimum_trend_observations,
        }


@dataclass(frozen=True, slots=True)
class InventoryInputReference:
    statement_id: int
    statement_item_id: int
    source_id: int
    revision_number: int
    fiscal_year: int
    fiscal_period: str
    item_code: str
    period_start: date | None
    period_end: date
    available_at: datetime
    publication_date: date
    publication_datetime: datetime | None

    def __post_init__(self) -> None:
        if (
            min(
                self.statement_id,
                self.statement_item_id,
                self.source_id,
                self.revision_number,
                self.fiscal_year,
            )
            < 1
        ):
            raise DomainValidationError("Inventory reference identity is invalid.")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise DomainValidationError("Inventory available_at must be aware.")
        object.__setattr__(self, "available_at", self.available_at.astimezone(UTC))
        if self.publication_datetime is not None:
            if (
                self.publication_datetime.tzinfo is None
                or self.publication_datetime.utcoffset() is None
            ):
                raise DomainValidationError("Inventory publication time must be aware.")
            object.__setattr__(
                self, "publication_datetime", self.publication_datetime.astimezone(UTC)
            )
        if self.period_start is not None and self.period_start > self.period_end:
            raise DomainValidationError("Inventory reference period is invalid.")
        if not self.item_code.strip() or self.fiscal_period != "FY":
            raise DomainValidationError(
                "Inventory references must identify annual FY data."
            )


@dataclass(frozen=True, slots=True)
class InventoryAnnualObservation:
    fiscal_year: int
    period_start: date | None
    period_end: date
    currency: str
    source_id: int
    accounting_standard: str
    consolidation_scope: str
    closing_inventory: Decimal | None
    cogs: Decimal | None
    inventory_reference: InventoryInputReference | None
    cogs_reference: InventoryInputReference | None
    cogs_unavailable_reason: str | None = None

    def __post_init__(self) -> None:
        if self.fiscal_year < 1 or self.source_id < 1:
            raise DomainValidationError("Inventory annual period is invalid.")
        if self.period_start is not None and self.period_start > self.period_end:
            raise DomainValidationError("Inventory annual period is invalid.")
        if len(self.currency) != 3 or not self.currency.isupper():
            raise DomainValidationError("Inventory currency is invalid.")
        for value in (self.closing_inventory, self.cogs):
            if value is not None and not value.is_finite():
                raise DomainValidationError("Inventory inputs must be finite Decimals.")


@dataclass(frozen=True, slots=True)
class InventorySnapshot:
    company_id: int
    security_id: int | None
    as_of: datetime
    fiscal_year: int
    period_start: date | None
    period_end: date
    closing_inventory: Decimal | None
    opening_inventory: Decimal | None
    average_inventory: Decimal | None
    cogs: Decimal | None
    inventory_change: Decimal | None
    inventory_growth: Decimal | None
    inventory_turnover: Decimal | None
    dio: Decimal | None
    trend: InventoryTrend
    status: InventoryStatus
    unavailable_reasons: tuple[str, ...]
    data_coverage: Decimal
    confidence: InventoryConfidence
    currency: str
    source_id: int
    calculation_version: int
    config_snapshot: dict[str, object]
    input_references: tuple[InventoryInputReference, ...]
    created_at: datetime | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if self.company_id < 1 or (
            self.security_id is not None and self.security_id < 1
        ):
            raise DomainValidationError("Inventory snapshot identity is invalid.")
        if self.source_id < 1 or self.fiscal_year < 1 or self.calculation_version < 1:
            raise DomainValidationError("Inventory snapshot provenance is invalid.")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DomainValidationError("Inventory as_of must be timezone-aware.")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
        if not Decimal(0) <= self.data_coverage <= Decimal(1):
            raise DomainValidationError("Inventory coverage must be in [0, 1].")
        if any(
            reference.available_at > self.as_of for reference in self.input_references
        ):
            raise DomainValidationError("Inventory input reference is after as_of.")
        if any(
            reference.source_id != self.source_id
            or reference.fiscal_year > self.fiscal_year
            or reference.period_end > self.period_end
            for reference in self.input_references
        ):
            raise DomainValidationError("Inventory input provenance is incompatible.")
