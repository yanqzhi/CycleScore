"""Time-bounded identifiers for a financial security."""

from dataclasses import dataclass
from datetime import date, datetime

from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.security_identifier import resolve_identifier_scope


@dataclass(frozen=True, slots=True)
class SecurityIdentifier:
    """A typed text identifier with optional exchange scope and validity dates."""

    security_id: int
    identifier_type: str
    identifier_value: str
    valid_from: date
    id: int | None = None
    exchange_id: int | None = None
    valid_to: date | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "identifier_type", self.identifier_type.strip().upper()
        )
        if self.security_id < 1 or (
            self.exchange_id is not None and self.exchange_id < 1
        ):
            raise DomainValidationError(
                "Identifier security and exchange IDs must be positive."
            )
        if not self.identifier_type.strip() or not self.identifier_value.strip():
            raise DomainValidationError("Identifier type and value are required.")
        resolve_identifier_scope(self.identifier_type, self.exchange_id)
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise DomainValidationError(
                "Identifier valid_to must not precede valid_from."
            )
