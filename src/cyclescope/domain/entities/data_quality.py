"""Immutable market-data quality report and append-oriented anomaly records."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.data_quality import (
    AnomalySeverity,
    AnomalyStatus,
    AnomalyType,
    CalendarStatus,
    DatasetType,
    QualityComponent,
    QualityDateRange,
    QualityStatus,
)


def _utc(field: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{field} must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    dataset_type: DatasetType
    date_range: QualityDateRange
    source_id: int | None
    as_of: datetime
    expected_sessions: int | None
    available_records: int
    missing_sessions: int | None
    coverage_ratio: Decimal | None
    components: tuple[QualityComponent, ...]
    score: Decimal | None
    config_version: str
    status: QualityStatus
    explanation: str
    calendar_status: CalendarStatus
    first_available_date: date | None = None
    last_available_date: date | None = None
    anomaly_counts: tuple[tuple[AnomalySeverity, int], ...] = ()
    config_snapshot: tuple[tuple[str, str], ...] = ()
    security_id: int | None = None
    base_currency: str | None = None
    quote_currency: str | None = None
    id: int | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", _utc("as_of", self.as_of))
        if self.created_at is not None:
            object.__setattr__(self, "created_at", _utc("created_at", self.created_at))
        if self.available_records < 0 or (
            self.source_id is not None and self.source_id < 1
        ):
            raise DomainValidationError("Report counts and source IDs must be valid.")
        if self.expected_sessions is not None and self.expected_sessions < 0:
            raise DomainValidationError("Expected sessions cannot be negative.")
        if self.missing_sessions is not None and self.missing_sessions < 0:
            raise DomainValidationError("Missing sessions cannot be negative.")
        if self.coverage_ratio is not None and (
            not self.coverage_ratio.is_finite()
            or self.coverage_ratio < 0
            or self.coverage_ratio > 100
        ):
            raise DomainValidationError("Coverage ratio must be between 0 and 100.")
        if self.score is not None and (
            not self.score.is_finite() or self.score < 0 or self.score > 100
        ):
            raise DomainValidationError("Quality score must be between 0 and 100.")
        if self.score is None and self.status not in (
            QualityStatus.INSUFFICIENT_DATA,
            QualityStatus.NOT_APPLICABLE,
        ):
            raise DomainValidationError(
                "Only insufficient/not-applicable reports omit a score."
            )
        if self.score is not None and self.status in (
            QualityStatus.INSUFFICIENT_DATA,
            QualityStatus.NOT_APPLICABLE,
        ):
            raise DomainValidationError(
                "Insufficient/not-applicable reports cannot have a score."
            )
        if not self.config_version.strip() or not self.explanation.strip():
            raise DomainValidationError("Report version and explanation are required.")
        if self.dataset_type == DatasetType.DAILY_PRICE and self.security_id is None:
            raise DomainValidationError("Price reports require security_id.")
        if self.dataset_type == DatasetType.FX_RATE and not (
            self.base_currency and self.quote_currency
        ):
            raise DomainValidationError("FX reports require a currency pair.")


@dataclass(frozen=True, slots=True)
class DataAnomaly:
    dataset_type: DatasetType
    observation_date: date
    source_id: int | None
    revision_number: int | None
    anomaly_type: AnomalyType
    severity: AnomalySeverity
    detection_rule: str
    detection_rule_version: str
    detected_at: datetime
    explanation: str
    quality_report_id: int | None = None
    security_id: int | None = None
    base_currency: str | None = None
    quote_currency: str | None = None
    detected_value: Decimal | None = None
    expected_value: Decimal | None = None
    daily_price_id: int | None = None
    fx_rate_id: int | None = None
    status: AnomalyStatus = AnomalyStatus.OPEN
    resolved_at: datetime | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "detected_at", _utc("detected_at", self.detected_at))
        if self.resolved_at is not None:
            object.__setattr__(
                self, "resolved_at", _utc("resolved_at", self.resolved_at)
            )
        if (self.source_id is not None and self.source_id < 1) or (
            self.revision_number is not None and self.revision_number < 1
        ):
            raise DomainValidationError("Anomaly source and revision must be valid.")
        if not self.detection_rule.strip() or not self.detection_rule_version.strip():
            raise DomainValidationError(
                "Anomaly detection rule and version are required."
            )
        if not self.explanation.strip():
            raise DomainValidationError("Anomaly explanation is required.")
        if self.dataset_type == DatasetType.DAILY_PRICE and self.security_id is None:
            raise DomainValidationError("Price anomaly requires security_id.")
        if self.dataset_type == DatasetType.FX_RATE and not (
            self.base_currency and self.quote_currency
        ):
            raise DomainValidationError("FX anomaly requires a currency pair.")
        terminal = self.status in (AnomalyStatus.RESOLVED, AnomalyStatus.FALSE_POSITIVE)
        if terminal != (self.resolved_at is not None):
            raise DomainValidationError("Terminal anomaly status requires resolved_at.")

    def transition(self, status: AnomalyStatus, at: datetime) -> "DataAnomaly":
        if self.status in (AnomalyStatus.RESOLVED, AnomalyStatus.FALSE_POSITIVE):
            raise DomainValidationError("Terminal anomalies cannot change status.")
        if status == AnomalyStatus.OPEN:
            raise DomainValidationError("Anomaly cannot transition back to OPEN.")
        if status == self.status:
            raise DomainValidationError("Anomaly status must change during transition.")
        resolved_at = (
            _utc("resolved_at", at)
            if status
            in (
                AnomalyStatus.RESOLVED,
                AnomalyStatus.FALSE_POSITIVE,
            )
            else None
        )
        from dataclasses import replace

        return replace(self, status=status, resolved_at=resolved_at)


@dataclass(frozen=True, slots=True)
class DataAnomalyLifecycleEvent:
    anomaly_id: int
    previous_status: AnomalyStatus
    new_status: AnomalyStatus
    transitioned_at: datetime
    actor: str | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if self.anomaly_id < 1:
            raise DomainValidationError("Lifecycle event anomaly ID must be positive.")
        object.__setattr__(
            self, "transitioned_at", _utc("transitioned_at", self.transitioned_at)
        )
        if self.previous_status == self.new_status:
            raise DomainValidationError("Lifecycle events require a status change.")
        if self.previous_status in (
            AnomalyStatus.RESOLVED,
            AnomalyStatus.FALSE_POSITIVE,
        ):
            raise DomainValidationError(
                "Terminal anomaly lifecycle events are invalid."
            )
        if self.new_status == AnomalyStatus.OPEN:
            raise DomainValidationError("Anomaly lifecycle cannot transition to OPEN.")
        if self.actor is not None and not self.actor.strip():
            raise DomainValidationError("Lifecycle event actor must be non-empty.")
