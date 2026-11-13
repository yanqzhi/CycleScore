"""Orchestrate acquisition through idempotent normalized persistence."""

from collections.abc import Callable
from datetime import UTC, datetime

from cyclescope.application.dto.ingestion import (
    DataFetchRequest,
    EmptyPayloadError,
    IngestionErrorCode,
    PipelineExecutionResult,
    PipelineIssue,
)
from cyclescope.application.interfaces.ingestion import (
    DataSourceAdapter,
    DataTransformer,
    DataValidator,
    IngestionRunRepository,
    NormalizedDataPersistence,
    RawDataRepository,
)
from cyclescope.domain.entities.ingestion import IngestionRun
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.ingestion import IngestionStatus


class ExecuteDataIngestionPipeline[NormalizedT]:
    """Run the provider-neutral pipeline; never commits caller-owned sessions.

    Failures are returned as typed issues and persisted on the run, so errors
    remain visible to the caller while successfully acquired raw bytes remain
    available for replay. The normalized persistence port must make its call
    atomic; run/raw persistence follows the caller's transaction boundary.
    """

    def __init__(
        self,
        adapter: DataSourceAdapter,
        transformer: DataTransformer[NormalizedT],
        validator: DataValidator[NormalizedT],
        raw_repository: RawDataRepository,
        run_repository: IngestionRunRepository,
        normalized_persistence: NormalizedDataPersistence[NormalizedT],
        *,
        max_payload_bytes: int = 50 * 1024 * 1024,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if max_payload_bytes < 1:
            raise ValueError("max_payload_bytes must be positive.")
        self.adapter = adapter
        self.transformer = transformer
        self.validator = validator
        self.raw_repository = raw_repository
        self.run_repository = run_repository
        self.normalized_persistence = normalized_persistence
        self.max_payload_bytes = max_payload_bytes
        self.clock = clock

    def execute(
        self, request: DataFetchRequest
    ) -> PipelineExecutionResult[NormalizedT]:
        run = self.run_repository.create(
            IngestionRun.start(request.source_id, request.dataset_code, self.clock())
        )
        issues: list[PipelineIssue] = []
        try:
            batch = self.adapter.fetch(request)
        except Exception as exc:
            code = (
                IngestionErrorCode.EMPTY_PAYLOAD
                if isinstance(exc, EmptyPayloadError)
                else IngestionErrorCode.ACQUISITION_FAILED
            )
            return self._failed(run, code, exc)

        if (
            batch.source_id != request.source_id
            or batch.dataset_code != request.dataset_code
        ):
            return self._failed(
                run,
                IngestionErrorCode.IDENTITY_MISMATCH,
                DomainValidationError(
                    "Adapter returned a different source or dataset."
                ),
            )
        if len(batch.payload) > self.max_payload_bytes:
            return self._failed(
                run,
                IngestionErrorCode.PAYLOAD_TOO_LARGE,
                DomainValidationError(
                    f"Payload exceeds the {self.max_payload_bytes}-byte limit."
                ),
            )
        try:
            raw_record = self.raw_repository.save(batch)
            if raw_record.id is None:
                raise DomainValidationError("Raw repository must assign a record ID.")
            run = self.run_repository.update(run.attach_raw_data_record(raw_record.id))
        except Exception as exc:
            return self._failed(run, IngestionErrorCode.RAW_PERSISTENCE_FAILED, exc)

        try:
            transformed = self.transformer.transform(batch)
        except Exception as exc:
            return self._failed(
                run,
                IngestionErrorCode.TRANSFORMATION_FAILED,
                exc,
                raw_data_record_id=raw_record.id,
                fetched_count=0,
            )
        if transformed.transformed_record_count == 0:
            issues.extend(transformed.errors)
            issues.append(
                PipelineIssue(
                    IngestionErrorCode.NO_RECORDS,
                    "Transformation produced no usable records.",
                )
            )
            failed_run = self._finish(
                run,
                IngestionStatus.FAILED,
                issues,
                raw_data_record_id=raw_record.id,
                fetched_count=transformed.source_record_count,
                transformed_count=0,
            )
            return PipelineExecutionResult(failed_run, (), (), tuple(issues))

        try:
            validation = self.validator.validate(transformed.records)
        except Exception as exc:
            return self._failed(
                run,
                IngestionErrorCode.VALIDATION_FAILED,
                exc,
                raw_data_record_id=raw_record.id,
                fetched_count=transformed.source_record_count,
                transformed_count=transformed.transformed_record_count,
            )

        issues.extend(transformed.errors)
        issues.extend(validation.errors)
        for rejected in validation.rejected_records:
            issues.extend(rejected.errors)
        persistence = None
        if validation.valid_records:
            try:
                persistence = self.normalized_persistence.persist_atomically(
                    validation.valid_records
                )
                if persistence.inserted_count + persistence.duplicate_count != len(
                    validation.valid_records
                ):
                    raise DomainValidationError(
                        "Normalized persistence counts do not match input records."
                    )
            except Exception as exc:
                return self._failed(
                    run,
                    IngestionErrorCode.NORMALIZED_PERSISTENCE_FAILED,
                    exc,
                    raw_data_record_id=raw_record.id,
                    fetched_count=transformed.source_record_count,
                    transformed_count=transformed.transformed_record_count,
                )
        inserted = persistence.inserted_count if persistence else 0
        duplicates = persistence.duplicate_count if persistence else 0
        partial = bool(
            transformed.errors or validation.rejected_records or validation.errors
        )
        final_status = IngestionStatus.PARTIAL if partial else IngestionStatus.SUCCEEDED
        finished = self._finish(
            run,
            final_status,
            issues,
            raw_data_record_id=raw_record.id,
            fetched_count=transformed.source_record_count,
            transformed_count=transformed.transformed_record_count,
            accepted_count=inserted,
            rejected_count=len(validation.rejected_records),
            duplicate_count=duplicates,
        )
        return PipelineExecutionResult(
            finished, validation.valid_records, validation.warnings, tuple(issues)
        )

    def _failed(
        self,
        run: IngestionRun,
        code: IngestionErrorCode,
        exc: Exception,
        *,
        raw_data_record_id: int | None = None,
        fetched_count: int = 0,
        transformed_count: int = 0,
    ) -> PipelineExecutionResult[NormalizedT]:
        issue = PipelineIssue(code, f"{type(exc).__name__}: {exc}")
        result_run = self._finish(
            run,
            IngestionStatus.FAILED,
            [issue],
            raw_data_record_id=raw_data_record_id,
            fetched_count=fetched_count,
            transformed_count=transformed_count,
        )
        return PipelineExecutionResult(result_run, (), (), (issue,))

    def _finish(
        self,
        run: IngestionRun,
        status: IngestionStatus,
        issues: list[PipelineIssue],
        *,
        raw_data_record_id: int | None = None,
        fetched_count: int = 0,
        transformed_count: int = 0,
        accepted_count: int = 0,
        rejected_count: int = 0,
        duplicate_count: int = 0,
    ) -> IngestionRun:
        error_code = issues[0].code.value if issues else None
        error_message = "; ".join(issue.message for issue in issues) or None
        completed = run.finish(
            status,
            self.clock(),
            raw_data_record_id=raw_data_record_id,
            fetched_count=fetched_count,
            transformed_count=transformed_count,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            duplicate_count=duplicate_count,
            error_code=error_code,
            error_message=error_message,
        )
        return self.run_repository.update(completed)
