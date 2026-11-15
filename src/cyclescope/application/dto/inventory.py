"""Requests and responses for inventory calculations."""

from dataclasses import dataclass
from datetime import UTC, datetime

from cyclescope.domain.entities.inventory import (
    InventoryConfig,
    InventorySnapshot,
    InventoryStatus,
)
from cyclescope.domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class CalculateInventoryRequest:
    company_id: int
    as_of: datetime
    security_id: int | None = None
    financial_source_id: int | None = None
    config: InventoryConfig = InventoryConfig()

    def __post_init__(self) -> None:
        if self.company_id < 1 or (
            self.security_id is not None and self.security_id < 1
        ):
            raise DomainValidationError("Inventory identity must be positive.")
        if self.financial_source_id is not None and self.financial_source_id < 1:
            raise DomainValidationError("financial_source_id must be positive.")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class CalculateInventoryResponse:
    snapshots: tuple[InventorySnapshot, ...]
    status: InventoryStatus
    unavailable_reason: str | None = None
