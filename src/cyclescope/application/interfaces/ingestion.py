"""Provider-independent acquisition, transform, validation, and persistence ports."""

from collections.abc import Sequence
from typing import Protocol, TypeVar

from cyclescope.application.dto.ingestion import (
    DataFetchRequest,
    NormalizedPersistenceResult,
    RawDataBatch,
    TransformationResult,
    ValidationResult,
)
from cyclescope.domain.entities.ingestion import IngestionRun, RawDataRecord

NormalizedT = TypeVar("NormalizedT")


class DataSourceAdapter(Protocol):
    def fetch(self, request: DataFetchRequest) -> RawDataBatch:
        """Acquire source bytes without applying domain transformations."""


class DataTransformer[NormalizedT](Protocol):
    def transform(self, batch: RawDataBatch) -> TransformationResult[NormalizedT]:
        """Transform bytes into common normalized records without persistence."""


class DataValidator[NormalizedT](Protocol):
    def validate(self, records: Sequence[NormalizedT]) -> ValidationResult[NormalizedT]:
        """Separate valid/rejected records and warnings without mutating values."""


class RawDataRepository(Protocol):
    def save(self, batch: RawDataBatch) -> RawDataRecord:
        """Append an acquisition event; equal checksums remain separate events."""


class IngestionRunRepository(Protocol):
    def create(self, run: IngestionRun) -> IngestionRun: ...

    def update(self, run: IngestionRun) -> IngestionRun: ...

    def get_by_id(self, run_id: int) -> IngestionRun | None: ...


class NormalizedDataPersistence[NormalizedT](Protocol):
    def persist_atomically(
        self, records: Sequence[NormalizedT]
    ) -> NormalizedPersistenceResult:
        """Idempotently insert records; on failure, roll back this entire call."""
