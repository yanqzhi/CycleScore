"""Deterministic infrastructure test adapters for the generic ingestion pipeline."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import TypeVar

from cyclescope.application.dto.ingestion import (
    DataFetchRequest,
    EmptyPayloadError,
    IngestionErrorCode,
    NormalizedPersistenceResult,
    PipelineIssue,
    RawDataBatch,
    RejectedRecord,
    TransformationResult,
    ValidationResult,
)
from cyclescope.domain.exceptions import DomainValidationError

NormalizedT = TypeVar("NormalizedT")


class MockDataSourceAdapter:
    """Return configured bytes and preserve request identity deterministically."""

    def __init__(
        self,
        payload: bytes,
        *,
        media_type: str = "application/octet-stream",
        fetched_at: datetime | None = None,
        source_available_at: datetime | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.media_type = media_type
        self.fetched_at = fetched_at or datetime(2026, 1, 1, tzinfo=UTC)
        self.source_available_at = source_available_at
        self.failure = failure
        self.requests: list[DataFetchRequest] = []

    def fetch(self, request: DataFetchRequest) -> RawDataBatch:
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        if not self.payload:
            raise EmptyPayloadError("Mock adapter returned an empty payload.")
        return RawDataBatch(
            source_id=request.source_id,
            dataset_code=request.dataset_code,
            payload=self.payload,
            media_type=self.media_type,
            fetched_at=self.fetched_at,
            source_available_at=self.source_available_at,
            provider_request_id="mock-request-1",
        )


class MockTransformer[NormalizedT]:
    """Return configured normalized records without mutating or storing them."""

    def __init__(
        self,
        records: Sequence[NormalizedT] = (),
        *,
        source_record_count: int | None = None,
        errors: tuple[PipelineIssue, ...] = (),
        failure: Exception | None = None,
    ) -> None:
        self.records = tuple(records)
        self.source_record_count = (
            source_record_count
            if source_record_count is not None
            else len(self.records)
        )
        self.errors = errors
        self.failure = failure
        self.batches: list[RawDataBatch] = []

    def transform(self, batch: RawDataBatch) -> TransformationResult[NormalizedT]:
        self.batches.append(batch)
        if self.failure is not None:
            raise self.failure
        return TransformationResult(
            self.records,
            self.errors,
            self.source_record_count,
            len(self.records),
        )


class MockValidator[NormalizedT]:
    """Reject selected records, emit warnings, and keep valid records unchanged."""

    def __init__(
        self,
        *,
        reject: Callable[[NormalizedT], bool] | None = None,
        warnings: tuple[PipelineIssue, ...] = (),
        failure: Exception | None = None,
    ) -> None:
        self.reject = reject or (lambda _: False)
        self.warnings = warnings
        self.failure = failure

    def validate(self, records: Sequence[NormalizedT]) -> ValidationResult[NormalizedT]:
        if self.failure is not None:
            raise self.failure
        valid: list[NormalizedT] = []
        rejected: list[RejectedRecord[NormalizedT]] = []
        for index, record in enumerate(records):
            if self.reject(record):
                rejected.append(
                    RejectedRecord(
                        record,
                        (
                            PipelineIssue(
                                IngestionErrorCode.VALIDATION_FAILED,
                                "Mock validator rejected record.",
                                str(index),
                            ),
                        ),
                    )
                )
            else:
                valid.append(record)
        return ValidationResult(tuple(valid), tuple(rejected), self.warnings)


class MockNormalizedDataPersistence[NormalizedT]:
    """Atomic in-memory normalized store with explicit idempotency keys."""

    def __init__(
        self,
        key: Callable[[NormalizedT], object] = lambda record: record,
        *,
        failure: Exception | None = None,
    ) -> None:
        self.key = key
        self.failure = failure
        self.records: dict[object, NormalizedT] = {}
        self.calls = 0

    def persist_atomically(
        self, records: Sequence[NormalizedT]
    ) -> NormalizedPersistenceResult:
        self.calls += 1
        staged: dict[object, NormalizedT] = {}
        duplicates = 0
        for record in records:
            record_key = self.key(record)
            if record_key in self.records or record_key in staged:
                duplicates += 1
            else:
                staged[record_key] = record
        if self.failure is not None:
            raise self.failure
        if duplicates + len(staged) != len(records):
            raise DomainValidationError("Invalid mock persistence accounting.")
        self.records.update(staged)
        return NormalizedPersistenceResult(len(staged), duplicates)
