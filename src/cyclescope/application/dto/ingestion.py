"""Provider-independent ingestion DTOs with immutable metadata and payloads."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from math import isfinite
from types import MappingProxyType

from cyclescope.domain.entities.ingestion import IngestionRun
from cyclescope.domain.exceptions import DomainValidationError

type JSONScalar = str | int | float | bool | None
_SENSITIVE_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "authorization",
    "apikey",
    "credential",
    "cookie",
)


def _normalize_utc(field_name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class DataFetchRequest:
    source_id: int
    dataset_code: str
    request_parameters: Mapping[str, JSONScalar]
    requested_at: datetime

    def __post_init__(self) -> None:
        if self.source_id < 1:
            raise DomainValidationError("source_id must be positive.")
        if not self.dataset_code.strip():
            raise DomainValidationError("dataset_code must not be empty.")
        copied: dict[str, JSONScalar] = {}
        for key, value in self.request_parameters.items():
            if not isinstance(key, str) or not key.strip():
                raise DomainValidationError(
                    "Request parameter keys must be non-empty strings."
                )
            normalized_key = key.casefold().replace("_", "").replace("-", "")
            if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS):
                raise DomainValidationError(
                    "Credentials must not be stored in request metadata."
                )
            if not isinstance(value, (str, int, float, bool, type(None))):
                raise DomainValidationError(
                    "Request parameters must be JSON scalar values."
                )
            if isinstance(value, float) and not isfinite(value):
                raise DomainValidationError(
                    "Request parameters cannot contain non-finite floats."
                )
            copied[key] = value
        object.__setattr__(self, "request_parameters", MappingProxyType(copied))
        object.__setattr__(
            self, "requested_at", _normalize_utc("requested_at", self.requested_at)
        )


class EmptyPayloadError(DomainValidationError):
    """Raised when an acquisition returns no bytes; empty imports are rejected."""


@dataclass(frozen=True, slots=True)
class RawDataBatch:
    source_id: int
    dataset_code: str
    payload: bytes
    media_type: str
    fetched_at: datetime
    source_available_at: datetime | None = None
    source_cursor: str | None = None
    provider_request_id: str | None = None
    sha256_checksum: str = field(init=False)

    def __post_init__(self) -> None:
        if self.source_id < 1 or not self.dataset_code.strip():
            raise DomainValidationError("Raw batch source and dataset are required.")
        if not isinstance(self.payload, bytes):
            raise DomainValidationError("payload must be immutable bytes.")
        if not self.payload:
            raise EmptyPayloadError("Acquired payload is empty.")
        if not self.media_type.strip():
            raise DomainValidationError("media_type is required.")
        object.__setattr__(self, "sha256_checksum", sha256(self.payload).hexdigest())
        object.__setattr__(
            self, "fetched_at", _normalize_utc("fetched_at", self.fetched_at)
        )
        if self.source_available_at is not None:
            object.__setattr__(
                self,
                "source_available_at",
                _normalize_utc("source_available_at", self.source_available_at),
            )


class IngestionErrorCode(StrEnum):
    EMPTY_PAYLOAD = "EMPTY_PAYLOAD"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    ACQUISITION_FAILED = "ACQUISITION_FAILED"
    RAW_PERSISTENCE_FAILED = "RAW_PERSISTENCE_FAILED"
    TRANSFORMATION_FAILED = "TRANSFORMATION_FAILED"
    INVALID_TRANSFORMATION_RESULT = "INVALID_TRANSFORMATION_RESULT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    NORMALIZED_PERSISTENCE_FAILED = "NORMALIZED_PERSISTENCE_FAILED"
    NO_RECORDS = "NO_RECORDS"


@dataclass(frozen=True, slots=True)
class PipelineIssue:
    code: IngestionErrorCode
    message: str
    source_location: str | None = None


@dataclass(frozen=True, slots=True)
class TransformationResult[NormalizedT]:
    records: tuple[NormalizedT, ...]
    errors: tuple[PipelineIssue, ...]
    source_record_count: int
    transformed_record_count: int

    def __post_init__(self) -> None:
        if self.source_record_count < 0 or self.transformed_record_count < 0:
            raise DomainValidationError(
                "Transformation record counts must be non-negative."
            )
        if self.transformed_record_count != len(self.records):
            raise DomainValidationError(
                "transformed_record_count must match records length."
            )
        if self.transformed_record_count > self.source_record_count:
            raise DomainValidationError("Transformed count cannot exceed source count.")


@dataclass(frozen=True, slots=True)
class RejectedRecord[NormalizedT]:
    record: NormalizedT
    errors: tuple[PipelineIssue, ...]

    def __post_init__(self) -> None:
        if not self.errors:
            raise DomainValidationError(
                "A rejected record requires a validation error."
            )


@dataclass(frozen=True, slots=True)
class ValidationResult[NormalizedT]:
    valid_records: tuple[NormalizedT, ...]
    rejected_records: tuple[RejectedRecord[NormalizedT], ...]
    warnings: tuple[PipelineIssue, ...] = ()
    errors: tuple[PipelineIssue, ...] = ()


@dataclass(frozen=True, slots=True)
class NormalizedPersistenceResult:
    inserted_count: int
    duplicate_count: int

    def __post_init__(self) -> None:
        if self.inserted_count < 0 or self.duplicate_count < 0:
            raise DomainValidationError("Persistence counts must be non-negative.")


@dataclass(frozen=True, slots=True)
class PipelineExecutionResult[NormalizedT]:
    run: IngestionRun
    valid_records: tuple[NormalizedT, ...]
    warnings: tuple[PipelineIssue, ...] = ()
    errors: tuple[PipelineIssue, ...] = ()
