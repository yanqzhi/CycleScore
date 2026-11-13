"""Industry domain entity."""

from dataclasses import dataclass

from cyclescope.domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class Industry:
    """A market industry with a stable uppercase code."""

    code: str
    name: str
    id: int | None = None
    is_active: bool = True

    def __post_init__(self) -> None:
        if not self.code or self.code != self.code.strip() or not self.code.isupper():
            raise DomainValidationError(
                "Industry code must be non-empty uppercase text."
            )
        if not self.name.strip():
            raise DomainValidationError("Industry name must not be empty.")
