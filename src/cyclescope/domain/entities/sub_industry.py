"""Sub-industry domain entity."""

from dataclasses import dataclass
from datetime import datetime

from cyclescope.domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class SubIndustry:
    """An industry subdivision with a stable code within its industry."""

    industry_id: int
    code: str
    name: str
    id: int | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.industry_id < 1:
            raise DomainValidationError("industry_id must be a positive integer.")
        if not self.code or self.code != self.code.strip() or not self.code.isupper():
            raise DomainValidationError("Sub-industry code must be uppercase text.")
        if not self.name.strip():
            raise DomainValidationError("Sub-industry name must not be empty.")
