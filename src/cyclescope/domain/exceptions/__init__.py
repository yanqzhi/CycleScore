"""Domain-specific exceptions."""


class DomainValidationError(ValueError):
    """Raised when a domain value violates a business rule."""
