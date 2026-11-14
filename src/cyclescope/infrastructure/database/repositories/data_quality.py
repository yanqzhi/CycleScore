"""SQLAlchemy adapter for persistent immutable quality assessments and anomalies."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cyclescope.application.interfaces.data_quality import DataQualityRepository
from cyclescope.domain.entities.data_quality import DataAnomaly, DataQualityReport
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.data_quality import (
    AnomalySeverity,
    AnomalyStatus,
    AnomalyType,
    CalendarStatus,
    DatasetType,
    QualityComponent,
    QualityComponentStatus,
    QualityDateRange,
    QualityStatus,
)
from cyclescope.infrastructure.database.models.data_quality import (
    DataAnomalyModel,
    DataQualityReportModel,
)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _report_entity(row: DataQualityReportModel) -> DataQualityReport:
    components = tuple(
        QualityComponent(
            name=item["name"] or "",
            score=Decimal(item["score"]) if item["score"] else None,
            weight=Decimal(item["weight"] or "0"),
            status=QualityComponentStatus(item["status"] or "UNAVAILABLE"),
            explanation=item["explanation"] or "Missing component explanation.",
        )
        for item in row.components
    )
    counts = tuple(
        (AnomalySeverity(str(item["severity"])), int(item["count"]))
        for item in row.anomaly_counts
    )
    return DataQualityReport(
        dataset_type=DatasetType(row.dataset_type),
        date_range=QualityDateRange(row.start_date, row.end_date),
        source_id=row.source_id,
        as_of=_utc(row.as_of),  # type: ignore[arg-type]
        expected_sessions=row.expected_sessions,
        available_records=row.available_records,
        missing_sessions=row.missing_sessions,
        coverage_ratio=Decimal(row.coverage_ratio)
        if row.coverage_ratio is not None
        else None,
        components=components,
        score=Decimal(row.score) if row.score is not None else None,
        config_version=row.config_version,
        status=QualityStatus(row.status),
        explanation=row.explanation,
        calendar_status=CalendarStatus(row.calendar_status),
        first_available_date=row.first_available_date,
        last_available_date=row.last_available_date,
        anomaly_counts=counts,
        config_snapshot=tuple(
            (str(item["name"]), str(item["value"])) for item in row.config_snapshot
        ),
        security_id=row.security_id,
        base_currency=row.base_currency,
        quote_currency=row.quote_currency,
        id=row.id,
        created_at=_utc(row.created_at),
    )


def _anomaly_entity(row: DataAnomalyModel) -> DataAnomaly:
    return DataAnomaly(
        dataset_type=DatasetType(row.dataset_type),
        observation_date=row.observation_date,
        source_id=row.source_id,
        revision_number=row.revision_number,
        anomaly_type=AnomalyType(row.anomaly_type),
        severity=AnomalySeverity(row.severity),
        detection_rule=row.detection_rule,
        detection_rule_version=row.detection_rule_version,
        detected_at=_utc(row.detected_at),  # type: ignore[arg-type]
        explanation=row.explanation,
        quality_report_id=row.quality_report_id,
        security_id=row.security_id,
        base_currency=row.base_currency,
        quote_currency=row.quote_currency,
        detected_value=Decimal(row.detected_value)
        if row.detected_value is not None
        else None,
        expected_value=Decimal(row.expected_value)
        if row.expected_value is not None
        else None,
        daily_price_id=row.daily_price_id,
        fx_rate_id=row.fx_rate_id,
        status=AnomalyStatus(row.status),
        resolved_at=_utc(row.resolved_at),
        id=row.id,
    )


class SQLAlchemyDataQualityRepository(DataQualityRepository):
    def __init__(self, session: Session) -> None:
        self._session = session

    def persist_assessment(
        self, report: DataQualityReport, anomalies: tuple[DataAnomaly, ...]
    ) -> tuple[DataQualityReport, tuple[DataAnomaly, ...]]:
        if report.id is not None or any(item.id is not None for item in anomalies):
            raise DomainValidationError("New quality assessments must be unpersisted.")
        with self._session.begin_nested():
            report_row = DataQualityReportModel(
                dataset_type=report.dataset_type.value,
                security_id=report.security_id,
                base_currency=report.base_currency,
                quote_currency=report.quote_currency,
                source_id=report.source_id,
                start_date=report.date_range.start_date,
                end_date=report.date_range.end_date,
                as_of=report.as_of,
                expected_sessions=report.expected_sessions,
                available_records=report.available_records,
                missing_sessions=report.missing_sessions,
                first_available_date=report.first_available_date,
                last_available_date=report.last_available_date,
                coverage_ratio=report.coverage_ratio,
                score=report.score,
                config_version=report.config_version,
                status=report.status.value,
                calendar_status=report.calendar_status.value,
                components=[
                    {
                        "name": item.name,
                        "score": str(item.score) if item.score is not None else None,
                        "weight": str(item.weight),
                        "status": item.status.value,
                        "explanation": item.explanation,
                    }
                    for item in report.components
                ],
                anomaly_counts=[
                    {"severity": severity.value, "count": count}
                    for severity, count in report.anomaly_counts
                ],
                config_snapshot=[
                    {"name": name, "value": value}
                    for name, value in report.config_snapshot
                ],
                explanation=report.explanation,
            )
            self._session.add(report_row)
            self._session.flush()
            anomaly_rows = [
                DataAnomalyModel(
                    quality_report_id=report_row.id,
                    dataset_type=item.dataset_type.value,
                    security_id=item.security_id,
                    base_currency=item.base_currency,
                    quote_currency=item.quote_currency,
                    observation_date=item.observation_date,
                    source_id=item.source_id,
                    revision_number=item.revision_number,
                    daily_price_id=item.daily_price_id,
                    fx_rate_id=item.fx_rate_id,
                    anomaly_type=item.anomaly_type.value,
                    severity=item.severity.value,
                    detected_value=item.detected_value,
                    expected_value=item.expected_value,
                    detection_rule=item.detection_rule,
                    detection_rule_version=item.detection_rule_version,
                    detected_at=item.detected_at,
                    status=item.status.value,
                    resolved_at=item.resolved_at,
                    explanation=item.explanation,
                )
                for item in anomalies
            ]
            self._session.add_all(anomaly_rows)
            self._session.flush()
            return _report_entity(report_row), tuple(
                _anomaly_entity(row) for row in anomaly_rows
            )

    def get_report(self, report_id: int) -> DataQualityReport | None:
        row = self._session.get(DataQualityReportModel, report_id)
        return _report_entity(row) if row is not None else None

    def get_anomaly(self, anomaly_id: int) -> DataAnomaly | None:
        row = self._session.get(DataAnomalyModel, anomaly_id)
        return _anomaly_entity(row) if row is not None else None

    def update_anomaly(self, anomaly: DataAnomaly) -> DataAnomaly:
        if anomaly.id is None:
            raise DomainValidationError("Anomaly update requires an ID.")
        row = self._session.get(DataAnomalyModel, anomaly.id)
        if row is None:
            raise DomainValidationError("Anomaly does not exist.")
        current = _anomaly_entity(row)
        static_current = replace(
            current, status=anomaly.status, resolved_at=anomaly.resolved_at
        )
        if static_current != anomaly:
            raise DomainValidationError("Anomaly detection history is immutable.")
        if current.status in (AnomalyStatus.RESOLVED, AnomalyStatus.FALSE_POSITIVE):
            raise DomainValidationError("Terminal anomalies cannot be modified.")
        row.status = anomaly.status.value
        row.resolved_at = anomaly.resolved_at
        self._session.flush()
        return _anomaly_entity(row)

    def list_anomalies(self, *, report_id: int | None = None) -> list[DataAnomaly]:
        statement = select(DataAnomalyModel).order_by(
            DataAnomalyModel.detected_at, DataAnomalyModel.id
        )
        if report_id is not None:
            statement = statement.where(DataAnomalyModel.quality_report_id == report_id)
        return [_anomaly_entity(row) for row in self._session.scalars(statement)]
