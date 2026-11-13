"""Security domain entity."""

from dataclasses import dataclass
from datetime import datetime

from cyclescope.domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class Security:
    """Tradable security listing."""

    company_id: int
    security_type: str
    id: int | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.company_id < 1:
            raise DomainValidationError("company_id must be a positive integer.")
        if not self.security_type.strip():
            raise DomainValidationError("security_type is required.")
