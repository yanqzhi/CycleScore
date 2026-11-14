"""CSV byte acquisition and market-data pipeline adapters."""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from sqlalchemy.orm import Session

from cyclescope.application.dto.ingestion import (
    DataFetchRequest,
    IngestionAdapterError,
    IngestionErrorCode,
    NormalizedPersistenceResult,
    PipelineIssue,
    RawDataBatch,
    RejectedRecord,
    TransformationResult,
    ValidationResult,
)
from cyclescope.application.dto.market_data import RawDailyPriceRecord, RawFxRateRecord
from cyclescope.application.dto.market_data_ingestion import (
    FX_DAILY_DATASET,
    PRICES_DAILY_DATASET,
    DailyPriceIngestionContext,
    FxRateIngestionContext,
)
from cyclescope.application.use_cases.market_data_validation import (
    daily_price_from_record,
    fx_rate_from_record,
)
from cyclescope.domain.entities.daily_price import DailyPrice
from cyclescope.domain.entities.fx_rate import FxRate
from cyclescope.domain.repositories.contracts import (
    DailyPriceRepository,
    FxRateRepository,
)
from cyclescope.domain.value_objects.market_data import CurrencyPair
from cyclescope.infrastructure.market_data.csv_provider import (
    CsvFormatError,
    parse_daily_price_csv,
    parse_fx_rate_csv,
)


class CsvMarketDataAdapter:
    """Acquire source bytes from configured CSV files; paths stay in Infrastructure."""

    def __init__(
        self,
        *,
        price_path: Path | None = None,
        fx_path: Path | None = None,
        max_payload_bytes: int = 50 * 1024 * 1024,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if max_payload_bytes < 1:
            raise ValueError("max_payload_bytes must be positive.")
        self._paths = {PRICES_DAILY_DATASET: price_path, FX_DAILY_DATASET: fx_path}
        self._max_payload_bytes = max_payload_bytes
        self._clock = clock

    def fetch(self, request: DataFetchRequest) -> RawDataBatch:
        if request.request_parameters:
            raise IngestionAdapterError(
                IngestionErrorCode.ACQUISITION_FAILED,
                "CSV imports do not support request parameters; filter the input "
                "file before import.",
            )
        if request.dataset_code not in self._paths:
            raise IngestionAdapterError(
                IngestionErrorCode.UNKNOWN_DATASET,
                f"Unsupported market-data dataset: {request.dataset_code}",
            )
        path = self._paths[request.dataset_code]
        if path is None:
            raise IngestionAdapterError(
                IngestionErrorCode.ACQUISITION_FAILED,
                f"No CSV file configured for {request.dataset_code}.",
            )
        try:
            if path.stat().st_size > self._max_payload_bytes:
                raise IngestionAdapterError(
                    IngestionErrorCode.PAYLOAD_TOO_LARGE,
                    f"Configured CSV exceeds the {self._max_payload_bytes}-byte limit.",
                )
            payload = path.read_bytes()
        except IngestionAdapterError:
            raise
        except OSError as exc:
            raise IngestionAdapterError(
                IngestionErrorCode.ACQUISITION_FAILED,
                f"Could not read configured CSV for {request.dataset_code}.",
            ) from exc
        return RawDataBatch(
            request.source_id,
            request.dataset_code,
            payload,
            "text/csv",
            self._clock(),
        )


class CsvMarketDataTransformer:
    """Convert retained CSV bytes into provider-neutral market-data row DTOs."""

    def transform(self, batch: RawDataBatch) -> TransformationResult[object]:
        try:
            if batch.dataset_code == PRICES_DAILY_DATASET:
                records: tuple[RawDailyPriceRecord, ...] | tuple[RawFxRateRecord, ...]
                records = parse_daily_price_csv(batch.payload)
            elif batch.dataset_code == FX_DAILY_DATASET:
                records = parse_fx_rate_csv(batch.payload)
            else:
                raise IngestionAdapterError(
                    IngestionErrorCode.UNKNOWN_DATASET,
                    f"Unsupported market-data dataset: {batch.dataset_code}",
                )
        except CsvFormatError as exc:
            raise IngestionAdapterError(
                IngestionErrorCode.INVALID_CSV, str(exc)
            ) from exc
        return TransformationResult(records, (), len(records), len(records))


class DailyPriceCsvValidator:
    def __init__(self, context: DailyPriceIngestionContext) -> None:
        self._context = context

    def validate(self, records: Sequence[object]) -> ValidationResult[DailyPrice]:
        valid: list[DailyPrice] = []
        rejected: list[RejectedRecord[object]] = []
        seen: set[tuple[int, object, int, int]] = set()
        for item in records:
            record = cast(RawDailyPriceRecord, item)
            try:
                entity = daily_price_from_record(record, self._context)
                key = (
                    entity.security_id,
                    entity.observation_date,
                    entity.source_id,
                    entity.revision_number,
                )
                if key in seen:
                    raise ValueError("Duplicate price record in CSV input.")
                seen.add(key)
                valid.append(entity)
            except (ValueError, TypeError) as exc:
                rejected.append(
                    RejectedRecord(
                        cast(object, record),
                        (
                            PipelineIssue(
                                IngestionErrorCode.DUPLICATE_RECORD
                                if "Duplicate" in str(exc)
                                else IngestionErrorCode.VALIDATION_FAILED,
                                str(exc),
                                f"row:{record.row_number}",
                            ),
                        ),
                    )
                )
        return ValidationResult(tuple(valid), tuple(rejected))


class FxRateCsvValidator:
    def __init__(self, context: FxRateIngestionContext) -> None:
        self._context = context

    def validate(self, records: Sequence[object]) -> ValidationResult[FxRate]:
        valid: list[FxRate] = []
        rejected: list[RejectedRecord[object]] = []
        seen: set[tuple[str, str, object, int, int]] = set()
        for item in records:
            record = cast(RawFxRateRecord, item)
            try:
                entity = fx_rate_from_record(record, self._context)
                key = (
                    entity.base_currency,
                    entity.quote_currency,
                    entity.observation_date,
                    entity.source_id,
                    entity.revision_number,
                )
                if key in seen:
                    raise ValueError("Duplicate FX record in CSV input.")
                seen.add(key)
                valid.append(entity)
            except (ValueError, TypeError) as exc:
                rejected.append(
                    RejectedRecord(
                        record,
                        (
                            PipelineIssue(
                                IngestionErrorCode.DUPLICATE_RECORD
                                if "Duplicate" in str(exc)
                                else IngestionErrorCode.VALIDATION_FAILED,
                                str(exc),
                                f"row:{record.row_number}",
                            ),
                        ),
                    )
                )
        return ValidationResult(tuple(valid), tuple(rejected))


class DailyPriceNormalizedPersistence:
    def __init__(self, repository: DailyPriceRepository, session: Session) -> None:
        self._repository = repository
        self._session = session

    def persist_atomically(
        self, records: Sequence[DailyPrice]
    ) -> NormalizedPersistenceResult:
        inserted = duplicates = 0
        with self._session.begin_nested():
            for record in records:
                if self._repository.exists(
                    record.security_id,
                    record.observation_date,
                    record.source_id,
                    record.revision_number,
                ):
                    duplicates += 1
                elif self._repository.save(record):
                    inserted += 1
                else:
                    duplicates += 1
        return NormalizedPersistenceResult(inserted, duplicates)


class FxRateNormalizedPersistence:
    def __init__(self, repository: FxRateRepository, session: Session) -> None:
        self._repository = repository
        self._session = session

    def persist_atomically(
        self, records: Sequence[FxRate]
    ) -> NormalizedPersistenceResult:
        inserted = duplicates = 0
        with self._session.begin_nested():
            for record in records:
                pair = CurrencyPair(record.base_currency, record.quote_currency)
                if self._repository.exists(
                    pair,
                    record.observation_date,
                    record.source_id,
                    record.revision_number,
                ):
                    duplicates += 1
                elif self._repository.save(record):
                    inserted += 1
                else:
                    duplicates += 1
        return NormalizedPersistenceResult(inserted, duplicates)
