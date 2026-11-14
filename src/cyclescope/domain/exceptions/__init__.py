"""Domain-specific exceptions."""


class DomainValidationError(ValueError):
    """Raised when a domain value violates a business rule."""


class DataUnavailable(Exception):
    """Raised when an otherwise valid query has no usable source data."""
