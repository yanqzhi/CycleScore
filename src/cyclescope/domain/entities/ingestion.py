"""Auditable ingestion and immutable raw-payload Domain entities."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256

from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.ingestion import IngestionStatus


def _utc(field: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{field} must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class RawDataRecord:
    source_id: int
    dataset_code: str
    payload: bytes
    media_type: str
    sha256_checksum: str
    fetched_at: datetime
    source_available_at: datetime | None = None
    source_cursor: str | None = None
    provider_request_id: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if self.source_id < 1 or not self.dataset_code.strip():
            raise DomainValidationError("Raw data source and dataset are required.")
        if not isinstance(self.payload, bytes) or not self.payload:
            raise DomainValidationError("Raw payload must be non-empty bytes.")
        if not self.media_type.strip():
            raise DomainValidationError("media_type is required.")
        if sha256(self.payload).hexdigest() != self.sha256_checksum:
            raise DomainValidationError(
                "Raw payload checksum does not match its bytes."
            )
        object.__setattr__(self, "fetched_at", _utc("fetched_at", self.fetched_at))
        if self.source_available_at is not None:
            object.__setattr__(
                self,
                "source_available_at",
                _utc("source_available_at", self.source_available_at),
            )


@dataclass(frozen=True, slots=True)
class IngestionRun:
    source_id: int
    dataset_code: str
    status: IngestionStatus
    started_at: datetime
    id: int | None = None
    completed_at: datetime | None = None
    raw_data_record_id: int | None = None
    fetched_count: int = 0
    transformed_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    duplicate_count: int = 0
    error_code: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.source_id < 1 or not self.dataset_code.strip():
            raise DomainValidationError(
                "Ingestion run source and dataset are required."
            )
        object.__setattr__(self, "started_at", _utc("started_at", self.started_at))
        if self.completed_at is not None:
            object.__setattr__(
                self, "completed_at", _utc("completed_at", self.completed_at)
            )
        if self.status == IngestionStatus.RUNNING and self.completed_at is not None:
            raise DomainValidationError("RUNNING runs cannot have completed_at.")
        if self.status != IngestionStatus.RUNNING and self.completed_at is None:
            raise DomainValidationError("Terminal runs require completed_at.")
        counts = (
            self.fetched_count,
            self.transformed_count,
            self.accepted_count,
            self.rejected_count,
            self.duplicate_count,
        )
        if any(
            not isinstance(count, int) or isinstance(count, bool) or count < 0
            for count in counts
        ):
            raise DomainValidationError(
                "Ingestion counts must be non-negative integers."
            )
        if self.accepted_count + self.rejected_count > self.transformed_count:
            raise DomainValidationError(
                "accepted_count + rejected_count cannot exceed transformed_count."
            )
        if self.raw_data_record_id is not None and self.raw_data_record_id < 1:
            raise DomainValidationError("raw_data_record_id must be positive.")

    @classmethod
    def start(
        cls, source_id: int, dataset_code: str, started_at: datetime
    ) -> "IngestionRun":
        return cls(source_id, dataset_code, IngestionStatus.RUNNING, started_at)

    def attach_raw_data_record(self, raw_data_record_id: int) -> "IngestionRun":
        if self.status != IngestionStatus.RUNNING:
            raise DomainValidationError("Raw data can only attach to a RUNNING run.")
        if raw_data_record_id < 1:
            raise DomainValidationError("raw_data_record_id must be positive.")
        return replace(self, raw_data_record_id=raw_data_record_id)

    def finish(
        self,
        status: IngestionStatus,
        completed_at: datetime,
        *,
        raw_data_record_id: int | None = None,
        fetched_count: int = 0,
        transformed_count: int = 0,
        accepted_count: int = 0,
        rejected_count: int = 0,
        duplicate_count: int = 0,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> "IngestionRun":
        if self.status != IngestionStatus.RUNNING:
            raise DomainValidationError("Only RUNNING ingestion runs may finish.")
        if status == IngestionStatus.RUNNING:
            raise DomainValidationError("finish requires a terminal status.")
        return replace(
            self,
            status=status,
            completed_at=completed_at,
            raw_data_record_id=raw_data_record_id,
            fetched_count=fetched_count,
            transformed_count=transformed_count,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            duplicate_count=duplicate_count,
            error_code=error_code,
            error_message=error_message,
        )
