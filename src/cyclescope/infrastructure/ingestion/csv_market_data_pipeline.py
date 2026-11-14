"""Explicit composition of the generic pipeline for CSV market-data imports."""

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from cyclescope.application.dto.ingestion import DataFetchRequest
from cyclescope.application.dto.market_data_ingestion import (
    FX_DAILY_DATASET,
    PRICES_DAILY_DATASET,
    DailyPriceIngestionContext,
    FxRateIngestionContext,
)
from cyclescope.application.use_cases.ingestion import ExecuteDataIngestionPipeline
from cyclescope.domain.repositories.contracts import (
    DailyPriceRepository,
    FxRateRepository,
)
from cyclescope.infrastructure.database.repositories.ingestion import (
    SQLAlchemyIngestionRunRepository,
    SQLAlchemyRawDataRepository,
)
from cyclescope.infrastructure.ingestion.adapters.csv_market_data_adapter import (
    CsvMarketDataAdapter,
    CsvMarketDataTransformer,
    DailyPriceCsvValidator,
    DailyPriceNormalizedPersistence,
    FxRateCsvValidator,
    FxRateNormalizedPersistence,
)


class CsvMarketDataIngestion:
    """Configure and execute price/FX imports while leaving commit to its caller."""

    def __init__(
        self,
        session: Session,
        price_repository: DailyPriceRepository,
        fx_repository: FxRateRepository,
        *,
        price_path: Path | None = None,
        fx_path: Path | None = None,
        max_payload_bytes: int = 50 * 1024 * 1024,
    ) -> None:
        self._session = session
        self._price_repository = price_repository
        self._fx_repository = fx_repository
        self._adapter = CsvMarketDataAdapter(price_path=price_path, fx_path=fx_path)
        self._max_payload_bytes = max_payload_bytes

    def import_prices(
        self, request: DataFetchRequest, context: DailyPriceIngestionContext
    ) -> Any:
        if (
            request.dataset_code != PRICES_DAILY_DATASET
            or request.source_id != context.source_id
        ):
            raise ValueError("Request and price context identities must match.")
        return self._pipeline(
            DailyPriceCsvValidator(context),
            DailyPriceNormalizedPersistence(self._price_repository, self._session),
        ).execute(request)

    def import_fx(
        self, request: DataFetchRequest, context: FxRateIngestionContext
    ) -> Any:
        if (
            request.dataset_code != FX_DAILY_DATASET
            or request.source_id != context.source_id
        ):
            raise ValueError("Request and FX context identities must match.")
        return self._pipeline(
            FxRateCsvValidator(context),
            FxRateNormalizedPersistence(self._fx_repository, self._session),
        ).execute(request)

    def _pipeline(self, validator: Any, persistence: Any) -> Any:
        return ExecuteDataIngestionPipeline(
            self._adapter,
            CsvMarketDataTransformer(),
            validator,
            SQLAlchemyRawDataRepository(self._session),
            SQLAlchemyIngestionRunRepository(self._session),
            persistence,
            max_payload_bytes=self._max_payload_bytes,
        )
