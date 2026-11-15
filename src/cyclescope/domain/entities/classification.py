"""Versioned external industry classifications and internal mappings."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from cyclescope.domain.exceptions import DomainValidationError


def _aware_utc(name: str, value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


def _code(name: str, value: str, max_length: int = 64) -> None:
    if (
        not value
        or value != value.strip()
        or len(value) > max_length
        or not value.isascii()
        or not (value[0].isalnum() and value[0].isascii())
        or not all(char.isupper() or char.isdigit() or char in "_.:-" for char in value)
    ):
        raise DomainValidationError(f"{name} must be a normalized uppercase code.")


@dataclass(frozen=True, slots=True)
class ClassificationScheme:
    scheme_code: str
    name: str
    publisher: str
    id: int | None = None
    description: str | None = None
    country_code: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        _code("scheme_code", self.scheme_code)
        if not self.name.strip() or not self.publisher.strip():
            raise DomainValidationError("Scheme name and publisher are required.")
        if self.country_code is not None and (
            len(self.country_code) != 2
            or not self.country_code.isascii()
            or not self.country_code.isalpha()
            or not self.country_code.isupper()
        ):
            raise DomainValidationError("country_code must be two uppercase letters.")
        object.__setattr__(
            self, "created_at", _aware_utc("created_at", self.created_at)
        )
        object.__setattr__(
            self, "updated_at", _aware_utc("updated_at", self.updated_at)
        )


@dataclass(frozen=True, slots=True)
class ClassificationVersion:
    scheme_id: int
    version_code: str
    effective_from: date
    effective_to: date | None = None
    published_at: datetime | None = None
    id: int | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.scheme_id < 1:
            raise DomainValidationError("scheme_id must be positive.")
        _code("version_code", self.version_code)
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise DomainValidationError("Version effective date range is invalid.")
        for name in ("published_at", "created_at", "updated_at"):
            object.__setattr__(self, name, _aware_utc(name, getattr(self, name)))

    def is_effective_on(self, effective_date: date) -> bool:
        return self.effective_from <= effective_date and (
            self.effective_to is None or effective_date <= self.effective_to
        )


class MappingMethod(StrEnum):
    EXACT = "EXACT"
    MANUAL = "MANUAL"
    APPROXIMATE = "APPROXIMATE"


@dataclass(frozen=True, slots=True)
class IndustryClassificationMapping:
    classification_version_id: int
    external_code: str
    external_name: str
    internal_industry_id: int
    valid_from: date
    mapping_method: MappingMethod
    internal_sub_industry_id: int | None = None
    valid_to: date | None = None
    confidence: Decimal | None = None
    notes: str | None = None
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if (
            self.classification_version_id < 1
            or self.internal_industry_id < 1
            or (
                self.internal_sub_industry_id is not None
                and self.internal_sub_industry_id < 1
            )
        ):
            raise DomainValidationError("Mapping reference IDs must be positive.")
        _code("external_code", self.external_code, max_length=120)
        if not self.external_name.strip():
            raise DomainValidationError("external_name is required.")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise DomainValidationError("Mapping validity range is invalid.")
        if not isinstance(self.mapping_method, MappingMethod):
            raise DomainValidationError("mapping_method is invalid.")
        if self.confidence is not None and (
            not self.confidence.is_finite()
            or not Decimal(0) <= self.confidence <= Decimal(1)
        ):
            raise DomainValidationError("confidence must be within [0, 1].")
        if self.notes is not None and len(self.notes) > 1000:
            raise DomainValidationError("notes must be at most 1000 characters.")
        for name in ("created_at", "updated_at"):
            object.__setattr__(self, name, _aware_utc(name, getattr(self, name)))

    def is_valid_on(self, effective_date: date) -> bool:
        return self.valid_from <= effective_date and (
            self.valid_to is None or effective_date <= self.valid_to
        )
