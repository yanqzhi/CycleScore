from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from cyclescope.application.dto.ingestion import (
    DataFetchRequest,
    IngestionErrorCode,
    PipelineIssue,
)
from cyclescope.application.use_cases.ingestion import (
    ExecuteDataIngestionPipeline,
    sanitize_error_message,
)
from cyclescope.domain.entities.ingestion import IngestionRun, RawDataRecord
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.ingestion import IngestionStatus
from cyclescope.infrastructure.database.models import CompanyModel, DataSourceModel
from cyclescope.infrastructure.database.models.financial_data import (
    FinancialStatementModel,
)
from cyclescope.infrastructure.database.models.ingestion import (
    RawDataRecordModel,
)
from cyclescope.infrastructure.database.repositories.ingestion import (
    SQLAlchemyIngestionRunRepository,
    SQLAlchemyRawDataRepository,
)
from cyclescope.infrastructure.database.session import create_database_engine
from cyclescope.infrastructure.ingestion.adapters.mock_adapter import (
    MockDataSourceAdapter,
    MockNormalizedDataPersistence,
    MockTransformer,
    MockValidator,
)

NOW = datetime(2026, 6, 1, 12, tzinfo=UTC)


@dataclass(frozen=True)
class Observation:
    key: str
    amount: int


def make_request(source_id: int, requested_at: datetime = NOW) -> DataFetchRequest:
    return DataFetchRequest(source_id, "prices.daily", {"symbol": "ABC"}, requested_at)


def make_pipeline(
    session,
    source_id: int,
    *,
    adapter=None,
    transformer=None,
    validator=None,
    raw_repository=None,
    normalized=None,
):
    return ExecuteDataIngestionPipeline(
        adapter or MockDataSourceAdapter(b"raw-payload", fetched_at=NOW),
        transformer or MockTransformer((Observation("a", 10),)),
        validator or MockValidator(),
        raw_repository or SQLAlchemyRawDataRepository(session),
        SQLAlchemyIngestionRunRepository(session),
        normalized or MockNormalizedDataPersistence(key=lambda row: row.key),
        max_payload_bytes=1024,
        clock=lambda: NOW + timedelta(minutes=1),
    )


def create_source(session) -> int:
    source = DataSourceModel(code="PIPE", name="Pipeline source", provider_type="mock")
    session.add(source)
    session.flush()
    return source.id


def test_success_preserves_payload_checksum_and_jst_request_normalization(session):
    source_id = create_source(session)
    original = {"symbol": "ABC"}
    request = DataFetchRequest(
        source_id,
        "prices.daily",
        original,
        datetime(2026, 6, 1, 21, tzinfo=timezone(timedelta(hours=9))),
    )
    original["symbol"] = "MUTATED"
    assert request.request_parameters["symbol"] == "ABC"
    assert request.requested_at == NOW
    adapter = MockDataSourceAdapter(
        b"\x00raw\xff",
        fetched_at=NOW,
        source_available_at=datetime(
            2026, 6, 1, 21, tzinfo=timezone(timedelta(hours=9))
        ),
    )
    normalized = MockNormalizedDataPersistence(key=lambda row: row.key)
    pipeline = make_pipeline(
        session,
        source_id,
        adapter=adapter,
        transformer=MockTransformer((Observation("a", 10),)),
        normalized=normalized,
    )
    result = pipeline.execute(request)
    assert result.run.status == IngestionStatus.SUCCEEDED
    assert result.run.fetched_count == result.run.transformed_count == 1
    assert result.run.accepted_count == 1
    raw = session.get(RawDataRecordModel, result.run.raw_data_record_id)
    assert raw is not None
    assert raw.payload == b"\x00raw\xff"
    assert raw.sha256 == sha256(b"\x00raw\xff").hexdigest()
    raw_entity = SQLAlchemyRawDataRepository(session).get_by_id(raw.id)
    assert raw_entity is not None and raw_entity.source_available_at == NOW
    assert normalized.records == {"a": Observation("a", 10)}


def test_identical_raw_acquisitions_remain_separate_and_normalized_data_is_idempotent(
    session,
):
    source_id = create_source(session)
    normalized = MockNormalizedDataPersistence(key=lambda row: row.key)
    pipeline = make_pipeline(session, source_id, normalized=normalized)
    first = pipeline.execute(make_request(source_id))
    second = pipeline.execute(make_request(source_id))
    assert first.run.raw_data_record_id != second.run.raw_data_record_id
    assert first.run.status == second.run.status == IngestionStatus.SUCCEEDED
    assert second.run.accepted_count == 0
    assert second.run.duplicate_count == 1
    assert session.scalar(
        select(RawDataRecordModel.id).order_by(RawDataRecordModel.id).limit(1)
    )
    assert session.query(RawDataRecordModel).count() == 2
    assert len(normalized.records) == 1


def test_acquisition_raw_and_empty_payload_failures_are_tracked(session):
    source_id = create_source(session)
    for adapter, expected in (
        (
            MockDataSourceAdapter(b"ok", failure=RuntimeError("offline")),
            IngestionErrorCode.ACQUISITION_FAILED,
        ),
        (MockDataSourceAdapter(b""), IngestionErrorCode.EMPTY_PAYLOAD),
    ):
        result = make_pipeline(session, source_id, adapter=adapter).execute(
            make_request(source_id)
        )
        assert result.run.status == IngestionStatus.FAILED
        assert result.run.error_code == expected.value
        assert result.run.completed_at is not None
    assert session.query(RawDataRecordModel).count() == 0

    class BrokenRawRepository:
        def save(self, batch):
            raise OSError("disk full")

    failed_raw = make_pipeline(
        session, source_id, raw_repository=BrokenRawRepository()
    ).execute(make_request(source_id))
    assert failed_raw.run.error_code == IngestionErrorCode.RAW_PERSISTENCE_FAILED.value
    assert session.query(RawDataRecordModel).count() == 0


def test_transform_failure_retains_raw_payload_for_replay(session):
    source_id = create_source(session)
    result = make_pipeline(
        session,
        source_id,
        transformer=MockTransformer(failure=RuntimeError("api_key=hidden-value")),
    ).execute(make_request(source_id))
    assert result.run.status == IngestionStatus.FAILED
    assert result.run.error_code == IngestionErrorCode.TRANSFORMATION_FAILED.value
    assert "hidden-value" not in (result.run.error_message or "")
    raw = session.get(RawDataRecordModel, result.run.raw_data_record_id)
    assert raw is not None and raw.payload == b"raw-payload"


def test_partial_transformation_and_validation_rejection_keep_valid_records(session):
    source_id = create_source(session)
    transform_error = PipelineIssue(
        IngestionErrorCode.TRANSFORMATION_FAILED, "row could not be parsed", "row:3"
    )
    transformer = MockTransformer(
        (Observation("keep", 1), Observation("reject", -1)),
        source_record_count=3,
        errors=(transform_error,),
    )
    normalized = MockNormalizedDataPersistence(key=lambda row: row.key)
    result = make_pipeline(
        session,
        source_id,
        transformer=transformer,
        validator=MockValidator(reject=lambda row: row.amount < 0),
        normalized=normalized,
    ).execute(make_request(source_id))
    assert result.run.status == IngestionStatus.PARTIAL
    assert (result.run.fetched_count, result.run.transformed_count) == (3, 2)
    assert (result.run.accepted_count, result.run.rejected_count) == (1, 1)
    assert result.valid_records == (Observation("keep", 1),)
    assert set(normalized.records) == {"keep"}
    assert result.errors[0].source_location == "row:3"
    raw = session.get(RawDataRecordModel, result.run.raw_data_record_id)
    assert raw is not None and raw.payload == b"raw-payload"


def test_normalized_persistence_failure_rolls_back_but_raw_is_preserved(session):
    source_id = create_source(session)
    normalized = MockNormalizedDataPersistence(
        key=lambda row: row.key, failure=RuntimeError("normalized store unavailable")
    )
    result = make_pipeline(session, source_id, normalized=normalized).execute(
        make_request(source_id)
    )
    assert result.run.status == IngestionStatus.FAILED
    assert (
        result.run.error_code == IngestionErrorCode.NORMALIZED_PERSISTENCE_FAILED.value
    )
    assert normalized.records == {}
    raw = session.get(RawDataRecordModel, result.run.raw_data_record_id)
    assert raw is not None and raw.payload == b"raw-payload"


def test_payload_limit_and_identity_mismatch_fail_before_raw_persistence(session):
    source_id = create_source(session)
    oversized = make_pipeline(
        session, source_id, adapter=MockDataSourceAdapter(b"x" * 1025)
    ).execute(make_request(source_id))
    assert oversized.run.error_code == IngestionErrorCode.PAYLOAD_TOO_LARGE.value

    class WrongIdentityAdapter:
        def fetch(self, request):
            from cyclescope.application.dto.ingestion import RawDataBatch

            return RawDataBatch(
                request.source_id + 1, request.dataset_code, b"x", "x/test", NOW
            )

    mismatch = make_pipeline(
        session, source_id, adapter=WrongIdentityAdapter()
    ).execute(make_request(source_id))
    assert mismatch.run.error_code == IngestionErrorCode.IDENTITY_MISMATCH.value
    assert session.query(RawDataRecordModel).count() == 0


def test_request_metadata_and_run_transitions_are_validated():
    with pytest.raises(DomainValidationError, match="Credentials"):
        DataFetchRequest(1, "dataset", {"api_key": "secret"}, NOW)
    with pytest.raises(DomainValidationError, match="non-empty bytes"):
        RawDataRecord(1, "dataset", b"", "x/test", "0" * 64, NOW)
    run = IngestionRun.start(1, "dataset", NOW)
    with pytest.raises(DomainValidationError, match="terminal status"):
        run.finish(IngestionStatus.RUNNING, NOW)
    completed = run.finish(IngestionStatus.SUCCEEDED, NOW)
    with pytest.raises(DomainValidationError, match="Only RUNNING"):
        completed.finish(IngestionStatus.FAILED, NOW)
    with pytest.raises(DomainValidationError, match="cannot exceed"):
        IngestionRun(
            1,
            "dataset",
            IngestionStatus.RUNNING,
            NOW,
            transformed_count=1,
            accepted_count=1,
            rejected_count=1,
        )


def test_error_sanitizer_redacts_authorization_and_secret_values():
    message = sanitize_error_message(
        "Authorization: Bearer abc123 api_key=xyz789 password: 'open sesame'"
    )
    assert "abc123" not in message
    assert "xyz789" not in message
    assert "open sesame" not in message
    assert message.count("[REDACTED]") == 3


def test_ingestion_migration_preserves_financial_rows_on_upgrade_and_downgrade(
    tmp_path: Path,
):
    database_path = tmp_path / "pipeline_migration.db"
    config = Config(str(Path.cwd() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "0006_financial_period_constraint")
    engine = create_database_engine(f"sqlite:///{database_path}")
    with Session(engine) as session:
        company = CompanyModel(name="Retained issuer", country_code="JP")
        source = DataSourceModel(
            code="RETAIN", name="Retained source", provider_type="test"
        )
        session.add_all([company, source])
        session.flush()
        statement = FinancialStatementModel(
            company_id=company.id,
            source_id=source.id,
            statement_type="PL",
            accounting_standard="IFRS",
            consolidation_scope="CONSOLIDATED",
            fiscal_year=2026,
            fiscal_period="Q1",
            period_start=datetime(2026, 1, 1).date(),
            period_end=datetime(2026, 3, 31).date(),
            publication_date=datetime(2026, 5, 15).date(),
            available_at=NOW,
            collected_at=NOW,
            revision_number=1,
            reporting_currency="USD",
        )
        session.add(statement)
        session.commit()
        statement_id = statement.id

    command.upgrade(config, "head")
    assert {"raw_data_records", "ingestion_runs"} <= set(
        inspect(engine).get_table_names()
    )
    with Session(engine) as session:
        assert session.get(FinancialStatementModel, statement_id) is not None
    command.downgrade(config, "0006_financial_period_constraint")
    assert not (
        {"raw_data_records", "ingestion_runs"} & set(inspect(engine).get_table_names())
    )
    with Session(engine) as session:
        assert session.get(FinancialStatementModel, statement_id) is not None
    command.upgrade(config, "head")
    assert {"raw_data_records", "ingestion_runs"} <= set(
        inspect(engine).get_table_names()
    )
    engine.dispose()
