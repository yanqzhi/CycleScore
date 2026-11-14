"""CSV price/FX imports through the reusable ingestion pipeline."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from cyclescope.application.dto.ingestion import (
    DataFetchRequest,
    IngestionAdapterError,
    IngestionErrorCode,
)
from cyclescope.application.dto.market_data_ingestion import (
    FX_DAILY_DATASET,
    PRICES_DAILY_DATASET,
    DailyPriceIngestionContext,
    FxRateIngestionContext,
)
from cyclescope.domain.value_objects.ingestion import IngestionStatus
from cyclescope.infrastructure.database.models import (
    CompanyModel,
    DailyPriceModel,
    DataSourceModel,
    FxRateModel,
    SecurityModel,
)
from cyclescope.infrastructure.database.models.ingestion import (
    IngestionRunModel,
    RawDataRecordModel,
)
from cyclescope.infrastructure.database.repositories.market_data import (
    SQLAlchemyDailyPriceRepository,
    SQLAlchemyFxRateRepository,
)
from cyclescope.infrastructure.ingestion.adapters.csv_market_data_adapter import (
    CsvMarketDataAdapter,
)
from cyclescope.infrastructure.ingestion.csv_market_data_pipeline import (
    CsvMarketDataIngestion,
)

NOW = datetime(2026, 5, 15, 16, tzinfo=UTC)


def _refs(session):
    company = CompanyModel(name="Pipeline issuer", country_code="JP")
    source = DataSourceModel(code="CSVPIPE", name="CSV Pipeline", provider_type="csv")
    session.add_all([company, source])
    session.flush()
    security = SecurityModel(company_id=company.id, security_type="common_stock")
    session.add(security)
    session.flush()
    return source.id, security.id


def _request(source_id: int, dataset: str) -> DataFetchRequest:
    return DataFetchRequest(source_id, dataset, {}, NOW)


def test_csv_price_pipeline_persists_idempotently_and_preserves_raw(
    session, tmp_path: Path
):
    source_id, security_id = _refs(session)
    path = tmp_path / "prices.csv"
    path.write_text(
        "date,open,high,low,close,volume,publication_date\n"
        "2026-05-14,10,12,9,11,100,2026-05-15\n",
        encoding="utf-8",
    )
    pipeline = CsvMarketDataIngestion(
        session,
        SQLAlchemyDailyPriceRepository(session),
        SQLAlchemyFxRateRepository(session),
        price_path=path,
    )
    context = DailyPriceIngestionContext(security_id, "usd", source_id, NOW, NOW, 1)
    first = pipeline.import_prices(_request(source_id, PRICES_DAILY_DATASET), context)
    second = pipeline.import_prices(_request(source_id, PRICES_DAILY_DATASET), context)
    assert first.run.status == IngestionStatus.SUCCEEDED
    assert (
        first.run.fetched_count,
        first.run.transformed_count,
        first.run.accepted_count,
    ) == (1, 1, 1)
    assert second.run.status == IngestionStatus.SUCCEEDED
    assert second.run.duplicate_count == 1
    assert session.scalar(select(DailyPriceModel.id)) is not None
    assert session.query(RawDataRecordModel).count() == 2


def test_fx_pipeline_and_row_level_validation(session, tmp_path: Path):
    source_id, _ = _refs(session)
    path = tmp_path / "fx.csv"
    path.write_text(
        "base_currency,quote_currency,date,rate\n"
        "USD,JPY,2026-05-14,155.25\n"
        "USD,JPY,2026-05-15,not-a-number\n"
        "USD,JPY,2026-05-16,156.1\n",
        encoding="utf-8",
    )
    pipeline = CsvMarketDataIngestion(
        session,
        SQLAlchemyDailyPriceRepository(session),
        SQLAlchemyFxRateRepository(session),
        fx_path=path,
    )
    context = FxRateIngestionContext("usd", "jpy", source_id, NOW, NOW, 1)
    result = pipeline.import_fx(_request(source_id, FX_DAILY_DATASET), context)
    assert result.run.status == IngestionStatus.PARTIAL
    assert (result.run.fetched_count, result.run.transformed_count) == (3, 3)
    assert (result.run.accepted_count, result.run.rejected_count) == (2, 1)
    assert result.errors[0].source_location == "row:3"
    rates = session.scalars(select(FxRateModel)).all()
    assert len(rates) == 2


def test_failed_normalized_flush_rolls_back_only_normalized_savepoint(
    session, tmp_path: Path, monkeypatch
):
    source_id, security_id = _refs(session)
    path = tmp_path / "prices.csv"
    path.write_text(
        "date,open,high,low,close,volume\n"
        "2026-05-13,10,12,9,11,100\n"
        "2026-05-14,10,12,9,11,100\n",
        encoding="utf-8",
    )
    repository = SQLAlchemyDailyPriceRepository(session)
    original_save = repository.save
    calls = 0

    def fail_second(record):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("normalized database unavailable")
        return original_save(record)

    monkeypatch.setattr(repository, "save", fail_second)
    pipeline = CsvMarketDataIngestion(
        session,
        repository,
        SQLAlchemyFxRateRepository(session),
        price_path=path,
    )
    context = DailyPriceIngestionContext(security_id, "USD", source_id, NOW, NOW, 1)
    result = pipeline.import_prices(_request(source_id, PRICES_DAILY_DATASET), context)
    assert result.run.status == IngestionStatus.FAILED
    assert result.run.error_code == IngestionErrorCode.NORMALIZED_PERSISTENCE_FAILED
    assert session.is_active
    assert session.scalar(select(DailyPriceModel.id)) is None
    assert session.get(RawDataRecordModel, result.run.raw_data_record_id) is not None
    persisted_run = session.get(IngestionRunModel, result.run.id)
    assert persisted_run is not None and persisted_run.status == "FAILED"
    session.commit()
    assert session.get(RawDataRecordModel, result.run.raw_data_record_id) is not None
    assert session.get(IngestionRunModel, result.run.id).status == "FAILED"


def test_caller_rollback_removes_the_whole_pipeline_unit_of_work(
    session, tmp_path: Path
):
    source_id, security_id = _refs(session)
    path = tmp_path / "prices.csv"
    path.write_text(
        "date,open,high,low,close,volume\n2026-05-14,10,12,9,11,100\n",
        encoding="utf-8",
    )
    pipeline = CsvMarketDataIngestion(
        session,
        SQLAlchemyDailyPriceRepository(session),
        SQLAlchemyFxRateRepository(session),
        price_path=path,
    )
    context = DailyPriceIngestionContext(security_id, "USD", source_id, NOW, NOW, 1)
    result = pipeline.import_prices(_request(source_id, PRICES_DAILY_DATASET), context)
    assert result.run.status == IngestionStatus.SUCCEEDED
    session.rollback()
    assert session.get(IngestionRunModel, result.run.id) is None
    assert session.get(RawDataRecordModel, result.run.raw_data_record_id) is None
    assert session.scalar(select(DailyPriceModel.id)) is None


def test_invalid_header_keeps_raw_batch_and_marks_run_failed(session, tmp_path: Path):
    source_id, security_id = _refs(session)
    path = tmp_path / "bad.csv"
    path.write_text("date,close\n2026-05-14,11\n", encoding="utf-8")
    pipeline = CsvMarketDataIngestion(
        session,
        SQLAlchemyDailyPriceRepository(session),
        SQLAlchemyFxRateRepository(session),
        price_path=path,
    )
    context = DailyPriceIngestionContext(security_id, "USD", source_id, NOW, NOW, 1)
    result = pipeline.import_prices(_request(source_id, PRICES_DAILY_DATASET), context)
    assert result.run.status == IngestionStatus.FAILED
    assert result.run.error_code == IngestionErrorCode.INVALID_CSV
    assert session.get(RawDataRecordModel, result.run.raw_data_record_id) is not None


def test_header_only_and_oversized_csv_fail_with_raw_retained(session, tmp_path: Path):
    source_id, security_id = _refs(session)
    path = tmp_path / "empty_rows.csv"
    path.write_text("date,open,high,low,close,volume\n", encoding="utf-8")
    base = CsvMarketDataIngestion(
        session,
        SQLAlchemyDailyPriceRepository(session),
        SQLAlchemyFxRateRepository(session),
        price_path=path,
    )
    context = DailyPriceIngestionContext(security_id, "USD", source_id, NOW, NOW, 1)
    empty = base.import_prices(_request(source_id, PRICES_DAILY_DATASET), context)
    assert empty.run.error_code == IngestionErrorCode.NO_RECORDS
    assert session.get(RawDataRecordModel, empty.run.raw_data_record_id) is not None

    path.write_bytes(b"x" * 1025)
    limited = CsvMarketDataIngestion(
        session,
        SQLAlchemyDailyPriceRepository(session),
        SQLAlchemyFxRateRepository(session),
        price_path=path,
        max_payload_bytes=1024,
    )
    oversized = limited.import_prices(
        _request(source_id, PRICES_DAILY_DATASET), context
    )
    assert oversized.run.error_code == IngestionErrorCode.PAYLOAD_TOO_LARGE
    assert oversized.run.raw_data_record_id is None


def test_csv_record_validator_rejects_wrong_pair_and_duplicate_rows(
    session, tmp_path: Path
):
    source_id, _ = _refs(session)
    path = tmp_path / "fx.csv"
    path.write_text(
        "base_currency,quote_currency,date,rate\n"
        "USD,JPY,2026-05-14,155.25\n"
        "USD,JPY,2026-05-14,155.25\n"
        "USD,JPY,2026-05-14,156.25\n"
        "EUR,JPY,2026-05-15,170.1\n",
        encoding="utf-8",
    )
    pipeline = CsvMarketDataIngestion(
        session,
        SQLAlchemyDailyPriceRepository(session),
        SQLAlchemyFxRateRepository(session),
        fx_path=path,
    )
    context = FxRateIngestionContext("USD", "JPY", source_id, NOW, NOW, 1)
    result = pipeline.import_fx(_request(source_id, FX_DAILY_DATASET), context)
    assert result.run.status == IngestionStatus.PARTIAL
    assert result.run.accepted_count == 1 and result.run.rejected_count == 3
    assert [issue.code for issue in result.errors] == [
        IngestionErrorCode.DUPLICATE_RECORD,
        IngestionErrorCode.DUPLICATE_CONFLICT,
        IngestionErrorCode.VALIDATION_FAILED,
    ]
    assert [issue.source_location for issue in result.errors] == [
        "row:3",
        "row:4",
        "row:5",
    ]


def test_run_rejects_completion_before_start():
    import pytest

    from cyclescope.domain.entities.ingestion import IngestionRun
    from cyclescope.domain.exceptions import DomainValidationError

    run = IngestionRun.start(1, "prices.daily", NOW)
    with pytest.raises(DomainValidationError, match="precede"):
        run.finish(IngestionStatus.SUCCEEDED, NOW - timedelta(seconds=1))


def test_csv_adapter_rejects_unsupported_parameters_and_checks_size_before_read(
    tmp_path: Path, monkeypatch
):
    path = tmp_path / "large.csv"
    path.write_bytes(b"x" * 20)
    adapter = CsvMarketDataAdapter(price_path=path, max_payload_bytes=10)

    def unexpected_read(_path):
        raise AssertionError("oversized input must be rejected before reading")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read)
    with pytest.raises(IngestionAdapterError) as error:
        adapter.fetch(_request(1, PRICES_DAILY_DATASET))
    assert error.value.pipeline_error_code == IngestionErrorCode.PAYLOAD_TOO_LARGE

    small = tmp_path / "small.csv"
    small.write_text("date,open,high,low,close,volume\n", encoding="utf-8")
    adapter = CsvMarketDataAdapter(price_path=small)
    unsupported = DataFetchRequest(
        1, PRICES_DAILY_DATASET, {"start_date": "2026-01-01"}, NOW
    )
    with pytest.raises(
        IngestionAdapterError, match="do not support request parameters"
    ):
        adapter.fetch(unsupported)
