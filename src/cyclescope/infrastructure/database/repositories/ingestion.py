"""SQLAlchemy adapters for raw acquisition and ingestion run tracking."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from cyclescope.application.dto.ingestion import RawDataBatch
from cyclescope.domain.entities.ingestion import IngestionRun, RawDataRecord
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    IngestionRunRepository as IngestionRunRepositoryContract,
)
from cyclescope.domain.repositories.contracts import (
    RawDataRecordRepository,
)
from cyclescope.domain.value_objects.ingestion import IngestionStatus
from cyclescope.infrastructure.database.models.ingestion import (
    IngestionRunModel,
    RawDataRecordModel,
)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _raw_entity(row: RawDataRecordModel) -> RawDataRecord:
    return RawDataRecord(
        id=row.id,
        source_id=row.source_id,
        dataset_code=row.dataset_code,
        payload=row.payload,
        media_type=row.media_type,
        sha256_checksum=row.sha256,
        fetched_at=_utc(row.fetched_at),  # type: ignore[arg-type]
        source_available_at=_utc(row.source_available_at),
        source_cursor=row.source_cursor,
        provider_request_id=row.provider_request_id,
    )


def _run_entity(row: IngestionRunModel) -> IngestionRun:
    return IngestionRun(
        id=row.id,
        source_id=row.source_id,
        dataset_code=row.dataset_code,
        status=IngestionStatus(row.status),
        started_at=_utc(row.started_at),  # type: ignore[arg-type]
        completed_at=_utc(row.completed_at),
        raw_data_record_id=row.raw_data_record_id,
        fetched_count=row.fetched_count,
        transformed_count=row.transformed_count,
        accepted_count=row.accepted_count,
        rejected_count=row.rejected_count,
        duplicate_count=row.duplicate_count,
        error_code=row.error_code,
        error_message=row.error_message,
    )


def _copy_run(run: IngestionRun, row: IngestionRunModel) -> None:
    row.source_id = run.source_id
    row.dataset_code = run.dataset_code
    row.status = run.status.value
    row.started_at = run.started_at
    row.completed_at = run.completed_at
    row.raw_data_record_id = run.raw_data_record_id
    row.fetched_count = run.fetched_count
    row.transformed_count = run.transformed_count
    row.accepted_count = run.accepted_count
    row.rejected_count = run.rejected_count
    row.duplicate_count = run.duplicate_count
    row.error_code = run.error_code
    row.error_message = run.error_message


class SQLAlchemyRawDataRepository(RawDataRecordRepository):
    """Append-only raw payload repository; checksum is not a unique key."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def save(self, batch: RawDataBatch) -> RawDataRecord:
        record = RawDataRecord(
            source_id=batch.source_id,
            dataset_code=batch.dataset_code,
            payload=batch.payload,
            media_type=batch.media_type,
            sha256_checksum=batch.sha256_checksum,
            fetched_at=batch.fetched_at,
            source_available_at=batch.source_available_at,
            source_cursor=batch.source_cursor,
            provider_request_id=batch.provider_request_id,
        )
        return self.create(record)

    def create(self, record: RawDataRecord) -> RawDataRecord:
        row = RawDataRecordModel(
            source_id=record.source_id,
            dataset_code=record.dataset_code,
            payload=record.payload,
            media_type=record.media_type,
            sha256=record.sha256_checksum,
            fetched_at=record.fetched_at,
            source_available_at=record.source_available_at,
            source_cursor=record.source_cursor,
            provider_request_id=record.provider_request_id,
        )
        self.session.add(row)
        self.session.flush()
        return _raw_entity(row)

    def get_by_id(self, record_id: int) -> RawDataRecord | None:
        row = self.session.get(RawDataRecordModel, record_id)
        return _raw_entity(row) if row is not None else None


class SQLAlchemyIngestionRunRepository(IngestionRunRepositoryContract):
    """Persistence adapter enforcing append-only lifecycle transitions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, run: IngestionRun) -> IngestionRun:
        if run.id is not None or run.status != IngestionStatus.RUNNING:
            raise DomainValidationError(
                "New ingestion runs must be unpersisted and RUNNING."
            )
        row = IngestionRunModel(
            source_id=run.source_id,
            dataset_code=run.dataset_code,
            status=run.status.value,
            started_at=run.started_at,
            completed_at=None,
            raw_data_record_id=run.raw_data_record_id,
            fetched_count=run.fetched_count,
            transformed_count=run.transformed_count,
            accepted_count=run.accepted_count,
            rejected_count=run.rejected_count,
            duplicate_count=run.duplicate_count,
            error_code=run.error_code,
            error_message=run.error_message,
        )
        self.session.add(row)
        self.session.flush()
        return _run_entity(row)

    def update(self, run: IngestionRun) -> IngestionRun:
        if run.id is None:
            raise DomainValidationError("Cannot update an ingestion run without an ID.")
        row = self.session.get(IngestionRunModel, run.id)
        if row is None:
            raise DomainValidationError("Ingestion run does not exist.")
        previous = _run_entity(row)
        if previous.status != IngestionStatus.RUNNING:
            if previous != run:
                raise DomainValidationError("Terminal ingestion runs are immutable.")
            return previous
        if (
            previous.source_id != run.source_id
            or previous.dataset_code != run.dataset_code
            or previous.started_at != run.started_at
        ):
            raise DomainValidationError("Ingestion run identity is immutable.")
        _copy_run(run, row)
        self.session.flush()
        return _run_entity(row)

    def get_by_id(self, run_id: int) -> IngestionRun | None:
        row = self.session.get(IngestionRunModel, run_id)
        return _run_entity(row) if row is not None else None
