"""Data-source domain entity."""

from dataclasses import dataclass
from datetime import datetime

from cyclescope.domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class DataSource:
    """Provider metadata without credentials or API secrets."""

    code: str
    name: str
    provider_type: str
    id: int | None = None
    website: str | None = None
    licensing_type: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if (
            not self.code.strip()
            or not self.name.strip()
            or not self.provider_type.strip()
        ):
            raise DomainValidationError(
                "Data source code, name, and provider type are required."
            )
