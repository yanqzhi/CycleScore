"""Deterministic market-data completeness, consistency, and outlier assessment."""

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from statistics import median
from typing import Any

from cyclescope.application.dto.data_quality import (
    FxQualityRequest,
    PriceQualityRequest,
    QualityAssessmentResult,
)
from cyclescope.application.interfaces.data_quality import (
    TradingCalendar,
    TradingCalendarNotConfigured,
)
from cyclescope.domain.entities import DailyPrice, FxRate
from cyclescope.domain.entities.data_quality import DataAnomaly, DataQualityReport
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.data_quality import (
    AnomalySeverity,
    AnomalyType,
    CalendarStatus,
    DataQualityConfig,
    DatasetType,
    QualityComponent,
    QualityComponentStatus,
    QualityDateRange,
    QualityStatus,
)


class MarketDataQualityAssessor:
    """Pure quality assessment service; never modifies source observations."""

    def __init__(self, config: DataQualityConfig | None = None) -> None:
        self.config = config or DataQualityConfig()

    def assess_prices(
        self,
        request: PriceQualityRequest,
        records: Sequence[DailyPrice],
        calendar: TradingCalendar | None,
        *,
        lookback_records: Sequence[DailyPrice] = (),
        detected_at: datetime | None = None,
    ) -> QualityAssessmentResult:
        if request.security_id < 1 or request.start_date > request.end_date:
            raise DomainValidationError("Invalid price quality request scope.")
        cutoff = _utc(request.as_of)
        candidates = (*records, *lookback_records)
        rows = tuple(
            row
            for row in candidates
            if row.security_id == request.security_id
            and request.start_date <= row.observation_date <= request.end_date
            and row.available_at <= cutoff
            and (request.source_id is None or row.source_id == request.source_id)
        )
        history = tuple(
            row
            for row in candidates
            if row.security_id == request.security_id
            and row.observation_date <= request.end_date
            and row.available_at <= cutoff
            and (request.source_id is None or row.source_id == request.source_id)
        )
        timestamp = _utc(detected_at or datetime.now(UTC))
        anomalies: list[DataAnomaly] = []
        anomalies.extend(self._price_duplicates(rows, timestamp))
        anomalies.extend(
            self._price_outliers(
                history, request.start_date, request.end_date, timestamp
            )
        )
        calendar_id = (
            f"EXCHANGE:{request.exchange_id}"
            if request.exchange_id is not None
            else None
        )
        sessions = self._sessions(
            calendar, calendar_id, request.start_date, request.end_date
        )
        anomalies.extend(
            self._missing_anomalies(
                DatasetType.DAILY_PRICE,
                sessions,
                {row.observation_date for row in rows},
                request.source_id,
                request.security_id,
                None,
                None,
                timestamp,
            )
        )
        report = self._report(
            dataset=DatasetType.DAILY_PRICE,
            date_range=QualityDateRange(request.start_date, request.end_date),
            source_id=request.source_id,
            as_of=cutoff,
            records=rows,
            sessions=sessions,
            anomalies=anomalies,
            outlier_records=history,
            security_id=request.security_id,
            detected_at=timestamp,
        )
        return QualityAssessmentResult(report, tuple(anomalies))

    def assess_fx(
        self,
        request: FxQualityRequest,
        records: Sequence[FxRate],
        calendar: TradingCalendar | None = None,
        *,
        lookback_records: Sequence[FxRate] = (),
        detected_at: datetime | None = None,
    ) -> QualityAssessmentResult:
        if request.start_date > request.end_date:
            raise DomainValidationError("Invalid FX quality request date range.")
        base, quote = (
            request.base_currency.strip().upper(),
            request.quote_currency.strip().upper(),
        )
        if not base or not quote or base == quote:
            raise DomainValidationError("Invalid FX quality currency pair.")
        cutoff = _utc(request.as_of)
        candidates = (*records, *lookback_records)
        rows = tuple(
            row
            for row in candidates
            if row.base_currency == base
            and row.quote_currency == quote
            and request.start_date <= row.observation_date <= request.end_date
            and row.available_at <= cutoff
            and (request.source_id is None or row.source_id == request.source_id)
        )
        history = tuple(
            row
            for row in candidates
            if row.base_currency == base
            and row.quote_currency == quote
            and row.observation_date <= request.end_date
            and row.available_at <= cutoff
            and (request.source_id is None or row.source_id == request.source_id)
        )
        timestamp = _utc(detected_at or datetime.now(UTC))
        anomalies = list(self._fx_duplicates(rows, timestamp))
        anomalies.extend(
            self._fx_outliers(history, request.start_date, request.end_date, timestamp)
        )
        sessions = self._sessions(
            calendar, "FX" if calendar else None, request.start_date, request.end_date
        )
        anomalies.extend(
            self._missing_anomalies(
                DatasetType.FX_RATE,
                sessions,
                {row.observation_date for row in rows},
                request.source_id,
                None,
                base,
                quote,
                timestamp,
            )
        )
        report = self._report(
            dataset=DatasetType.FX_RATE,
            date_range=QualityDateRange(request.start_date, request.end_date),
            source_id=request.source_id,
            as_of=cutoff,
            records=rows,
            sessions=sessions,
            anomalies=anomalies,
            outlier_records=history,
            base_currency=base,
            quote_currency=quote,
            detected_at=timestamp,
        )
        return QualityAssessmentResult(report, tuple(anomalies))

    def _sessions(
        self,
        calendar: TradingCalendar | None,
        calendar_id: str | None,
        start: date,
        end: date,
    ) -> tuple[date, ...] | None:
        if calendar is None or calendar_id is None:
            return None
        try:
            sessions = calendar.expected_sessions(calendar_id, start, end)
        except TradingCalendarNotConfigured:
            return None
        return tuple(
            sorted({session for session in sessions if start <= session <= end})
        )

    def _price_duplicates(
        self, rows: Sequence[DailyPrice], at: datetime
    ) -> list[DataAnomaly]:
        grouped: dict[tuple[int, date, int, int], list[DailyPrice]] = defaultdict(list)
        for row in rows:
            grouped[
                (
                    row.security_id,
                    row.observation_date,
                    row.source_id,
                    row.revision_number,
                )
            ].append(row)
        anomalies: list[DataAnomaly] = []
        for group in grouped.values():
            if len(group) < 2:
                continue
            first = group[0]
            exact = all(
                (item.open, item.high, item.low, item.close, item.volume)
                == (first.open, first.high, first.low, first.close, first.volume)
                for item in group[1:]
            )
            anomalies.append(
                self._anomaly(
                    DatasetType.DAILY_PRICE,
                    first.observation_date,
                    first.source_id,
                    first.revision_number,
                    AnomalyType.DUPLICATE_EXACT
                    if exact
                    else AnomalyType.DUPLICATE_CONFLICT,
                    AnomalySeverity.INFO if exact else AnomalySeverity.ERROR,
                    f"Duplicate natural key has {len(group)} observations.",
                    at,
                    security_id=first.security_id,
                )
            )
        by_date: dict[date, list[DailyPrice]] = defaultdict(list)
        for row in rows:
            by_date[row.observation_date].append(row)
        for group in by_date.values():
            for index, left in enumerate(group):
                for right in group[index + 1 :]:
                    if left.source_id != right.source_id and left.close != right.close:
                        anomalies.append(
                            self._anomaly(
                                DatasetType.DAILY_PRICE,
                                left.observation_date,
                                left.source_id,
                                left.revision_number,
                                AnomalyType.DUPLICATE_CONFLICT,
                                AnomalySeverity.WARNING,
                                f"Source {right.source_id} reports a different close; "
                                "sources remain distinct.",
                                at,
                                security_id=left.security_id,
                                detected_value=left.close,
                                expected_value=right.close,
                            )
                        )
        return anomalies

    def _fx_duplicates(self, rows: Sequence[FxRate], at: datetime) -> list[DataAnomaly]:
        grouped: dict[tuple[str, str, date, int, int], list[FxRate]] = defaultdict(list)
        for row in rows:
            grouped[
                (
                    row.base_currency,
                    row.quote_currency,
                    row.observation_date,
                    row.source_id,
                    row.revision_number,
                )
            ].append(row)
        anomalies: list[DataAnomaly] = []
        for group in grouped.values():
            if len(group) > 1:
                first = group[0]
                exact = all(row.rate == first.rate for row in group[1:])
                anomalies.append(
                    self._anomaly(
                        DatasetType.FX_RATE,
                        first.observation_date,
                        first.source_id,
                        first.revision_number,
                        AnomalyType.DUPLICATE_EXACT
                        if exact
                        else AnomalyType.DUPLICATE_CONFLICT,
                        AnomalySeverity.INFO if exact else AnomalySeverity.ERROR,
                        f"Duplicate natural key has {len(group)} observations.",
                        at,
                        base_currency=first.base_currency,
                        quote_currency=first.quote_currency,
                    )
                )
        by_date: dict[date, list[FxRate]] = defaultdict(list)
        for row in rows:
            by_date[row.observation_date].append(row)
        for group in by_date.values():
            for index, left in enumerate(group):
                for right in group[index + 1 :]:
                    if left.source_id != right.source_id and left.rate != right.rate:
                        anomalies.append(
                            self._anomaly(
                                DatasetType.FX_RATE,
                                left.observation_date,
                                left.source_id,
                                left.revision_number,
                                AnomalyType.DUPLICATE_CONFLICT,
                                AnomalySeverity.WARNING,
                                f"Source {right.source_id} reports a different rate; "
                                "sources remain distinct.",
                                at,
                                base_currency=left.base_currency,
                                quote_currency=left.quote_currency,
                                detected_value=left.rate,
                                expected_value=right.rate,
                            )
                        )
        return anomalies

    def _price_outliers(
        self,
        rows: Sequence[DailyPrice],
        report_start: date,
        report_end: date,
        at: datetime,
    ) -> list[DataAnomaly]:
        result: list[DataAnomaly] = []
        by_source: dict[int, list[DailyPrice]] = defaultdict(list)
        for row in rows:
            by_source[row.source_id].append(row)
        for source_rows in by_source.values():
            source_rows.sort(key=lambda row: row.observation_date)
            for index, row in enumerate(source_rows):
                in_report = report_start <= row.observation_date <= report_end
                if in_report and index and source_rows[index - 1].close > 0:
                    prior = source_rows[index - 1]
                    change = abs(row.close - prior.close) / prior.close
                    if change > self.config.price_move_threshold:
                        result.append(
                            self._anomaly(
                                DatasetType.DAILY_PRICE,
                                row.observation_date,
                                row.source_id,
                                row.revision_number,
                                AnomalyType.PRICE_MOVE,
                                self._severity(
                                    change, self.config.price_move_threshold
                                ),
                                f"Absolute close move {change:.4%} exceeds configured "
                                f"threshold {self.config.price_move_threshold:.2%}; "
                                "review for corporate actions.",
                                at,
                                security_id=row.security_id,
                                detected_value=change,
                                expected_value=self.config.price_move_threshold,
                                daily_price_id=row.id,
                            )
                        )
                history = source_rows[max(0, index - 20) : index]
                if in_report and len(history) >= 5:
                    typical = Decimal(str(median([item.volume for item in history])))
                    if (
                        typical > 0
                        and Decimal(row.volume)
                        > typical * self.config.volume_median_multiple
                    ):
                        ratio = Decimal(row.volume) / typical
                        result.append(
                            self._anomaly(
                                DatasetType.DAILY_PRICE,
                                row.observation_date,
                                row.source_id,
                                row.revision_number,
                                AnomalyType.ABNORMAL_VOLUME,
                                AnomalySeverity.WARNING,
                                f"Volume is {ratio:.2f} times the prior rolling "
                                "median.",
                                at,
                                security_id=row.security_id,
                                detected_value=ratio,
                                expected_value=self.config.volume_median_multiple,
                                daily_price_id=row.id,
                            )
                        )
        return result

    def _fx_outliers(
        self,
        rows: Sequence[FxRate],
        report_start: date,
        report_end: date,
        at: datetime,
    ) -> list[DataAnomaly]:
        result: list[DataAnomaly] = []
        by_source: dict[int, list[FxRate]] = defaultdict(list)
        for row in rows:
            by_source[row.source_id].append(row)
        for source_rows in by_source.values():
            source_rows.sort(key=lambda row: row.observation_date)
            for prior, row in zip(source_rows, source_rows[1:], strict=False):
                if not report_start <= row.observation_date <= report_end:
                    continue
                change = abs(row.rate - prior.rate) / prior.rate
                if change > self.config.fx_move_threshold:
                    result.append(
                        self._anomaly(
                            DatasetType.FX_RATE,
                            row.observation_date,
                            row.source_id,
                            row.revision_number,
                            AnomalyType.FX_MOVE,
                            self._severity(change, self.config.fx_move_threshold),
                            f"Absolute FX move {change:.4%} exceeds configured "
                            f"threshold {self.config.fx_move_threshold:.2%}.",
                            at,
                            base_currency=row.base_currency,
                            quote_currency=row.quote_currency,
                            detected_value=change,
                            expected_value=self.config.fx_move_threshold,
                            fx_rate_id=row.id,
                        )
                    )
        return result

    def _report(
        self,
        *,
        dataset: DatasetType,
        date_range: QualityDateRange,
        source_id: int | None,
        as_of: datetime,
        records: Sequence[DailyPrice | FxRate],
        sessions: tuple[date, ...] | None,
        anomalies: Sequence[DataAnomaly],
        outlier_records: Sequence[DailyPrice | FxRate],
        detected_at: datetime,
        security_id: int | None = None,
        base_currency: str | None = None,
        quote_currency: str | None = None,
    ) -> DataQualityReport:
        if sessions is None:
            expected = missing = coverage = None
            completeness = QualityComponent(
                "completeness",
                None,
                self._weight("completeness"),
                QualityComponentStatus.UNAVAILABLE,
                "UNKNOWN_CALENDAR: no exchange-specific trading calendar is "
                "configured.",
            )
            status = QualityStatus.INSUFFICIENT_DATA
            calendar_status = CalendarStatus.UNKNOWN_CALENDAR
        else:
            expected = len(sessions)
            observed = {row.observation_date for row in records}
            available = len(observed.intersection(sessions))
            missing = expected - available
            if expected == 0:
                coverage = None
                completeness = QualityComponent(
                    "completeness",
                    None,
                    self._weight("completeness"),
                    QualityComponentStatus.UNAVAILABLE,
                    "No expected trading sessions exist in this range "
                    "(NOT_APPLICABLE).",
                )
                status = QualityStatus.NOT_APPLICABLE
                calendar_status = CalendarStatus.NOT_APPLICABLE
            else:
                coverage = Decimal(available) * 100 / Decimal(expected)
                completeness = QualityComponent(
                    "completeness",
                    coverage,
                    self._weight("completeness"),
                    QualityComponentStatus.PASSED
                    if missing == 0
                    else QualityComponentStatus.WARNING,
                    f"{available}/{expected} expected sessions are available; "
                    f"{missing} missing.",
                )
                status = QualityStatus.PASS
                calendar_status = CalendarStatus.KNOWN
        components = [completeness]
        if records:
            required_history = 6 if dataset == DatasetType.DAILY_PRICE else 2
            histories: dict[int, set[date]] = defaultdict(set)
            for record in outlier_records:
                histories[record.source_id].add(record.observation_date)
            outliers_available = bool(histories) and all(
                len(days) >= required_history for days in histories.values()
            )
            components.extend(
                (
                    QualityComponent(
                        "structural_validity",
                        Decimal(100),
                        self._weight("structural_validity"),
                        QualityComponentStatus.PASSED,
                        "All supplied Domain entities passed structural validation.",
                    ),
                    QualityComponent(
                        "consistency",
                        self._consistency_score(anomalies),
                        self._weight("consistency"),
                        QualityComponentStatus.WARNING
                        if any(
                            a.severity
                            in (AnomalySeverity.ERROR, AnomalySeverity.CRITICAL)
                            for a in anomalies
                        )
                        else QualityComponentStatus.PASSED,
                        "Duplicate and cross-source consistency checks were applied.",
                    ),
                    QualityComponent(
                        "outlier_assessment",
                        self._outlier_score(anomalies) if outliers_available else None,
                        self._weight("outlier_assessment"),
                        QualityComponentStatus.UNAVAILABLE
                        if not outliers_available
                        else QualityComponentStatus.WARNING
                        if any(
                            a.anomaly_type
                            in (
                                AnomalyType.PRICE_MOVE,
                                AnomalyType.FX_MOVE,
                                AnomalyType.ABNORMAL_VOLUME,
                            )
                            for a in anomalies
                        )
                        else QualityComponentStatus.PASSED,
                        (
                            "Configurable movement and rolling-volume thresholds "
                            "were applied."
                            if outliers_available
                            else (
                                f"Outlier checks need {required_history} observations "
                                "per source."
                            )
                        ),
                    ),
                    QualityComponent(
                        "provenance",
                        Decimal(100),
                        self._weight("provenance"),
                        QualityComponentStatus.PASSED,
                        "Source, revision, available_at, and collected_at are "
                        "present on all observations.",
                    ),
                )
            )
        else:
            for name in (
                "structural_validity",
                "consistency",
                "outlier_assessment",
                "provenance",
            ):
                components.append(
                    QualityComponent(
                        name,
                        None,
                        self._weight(name),
                        QualityComponentStatus.UNAVAILABLE,
                        "No observations are available for assessment.",
                    )
                )
            if status == QualityStatus.PASS:
                status = QualityStatus.INSUFFICIENT_DATA
        score = None
        if all(component.score is not None for component in components):
            score = sum(
                (
                    component.score * component.weight
                    for component in components
                    if component.score is not None
                ),
                Decimal(0),
            )
            if status == QualityStatus.PASS:
                if any(
                    a.severity in (AnomalySeverity.ERROR, AnomalySeverity.CRITICAL)
                    for a in anomalies
                ):
                    status = QualityStatus.FAIL
                elif any(a.severity == AnomalySeverity.WARNING for a in anomalies) or (
                    coverage is not None and coverage < 100
                ):
                    status = QualityStatus.WARNING
        if status != QualityStatus.NOT_APPLICABLE and any(
            component.score is None for component in components
        ):
            status = QualityStatus.INSUFFICIENT_DATA
        explanation = (
            "; ".join(
                component.explanation
                for component in components
                if component.status
                in (
                    QualityComponentStatus.WARNING,
                    QualityComponentStatus.FAILED,
                    QualityComponentStatus.UNAVAILABLE,
                )
            )
            or "All configured quality checks passed."
        )
        if status == QualityStatus.NOT_APPLICABLE:
            score = None
        if status == QualityStatus.INSUFFICIENT_DATA:
            score = None
        return DataQualityReport(
            dataset_type=dataset,
            date_range=date_range,
            source_id=source_id,
            as_of=as_of,
            expected_sessions=expected,
            available_records=len(records),
            missing_sessions=missing,
            coverage_ratio=coverage,
            components=tuple(components),
            score=score,
            config_version=self.config.version,
            status=status,
            explanation=explanation,
            calendar_status=calendar_status,
            security_id=security_id,
            base_currency=base_currency,
            quote_currency=quote_currency,
            first_available_date=min(
                (row.observation_date for row in records), default=None
            ),
            last_available_date=max(
                (row.observation_date for row in records), default=None
            ),
            anomaly_counts=tuple(
                (severity, sum(item.severity == severity for item in anomalies))
                for severity in AnomalySeverity
            ),
            config_snapshot=(
                ("price_move_threshold", str(self.config.price_move_threshold)),
                ("fx_move_threshold", str(self.config.fx_move_threshold)),
                ("volume_median_multiple", str(self.config.volume_median_multiple)),
                *(
                    (f"weight.{name}", str(weight))
                    for name, weight in self.config.weights
                ),
            ),
        )

    @staticmethod
    def _consistency_score(anomalies: Sequence[DataAnomaly]) -> Decimal:
        conflicts = sum(
            a.anomaly_type == AnomalyType.DUPLICATE_CONFLICT for a in anomalies
        )
        return max(Decimal(0), Decimal(100 - conflicts * 20))

    def _weight(self, name: str) -> Decimal:
        return dict(self.config.weights)[name]

    @staticmethod
    def _outlier_score(anomalies: Sequence[DataAnomaly]) -> Decimal:
        penalties = {
            AnomalySeverity.INFO: 0,
            AnomalySeverity.WARNING: 5,
            AnomalySeverity.ERROR: 15,
            AnomalySeverity.CRITICAL: 30,
        }
        total = sum(
            penalties[a.severity]
            for a in anomalies
            if a.anomaly_type
            not in (
                AnomalyType.DUPLICATE_EXACT,
                AnomalyType.DUPLICATE_CONFLICT,
                AnomalyType.MISSING_SESSION,
            )
        )
        return max(Decimal(0), Decimal(100 - total))

    def _severity(self, value: Decimal, threshold: Decimal) -> AnomalySeverity:
        return (
            AnomalySeverity.CRITICAL if value > threshold * 2 else AnomalySeverity.ERROR
        )

    def _missing_anomalies(
        self,
        dataset: DatasetType,
        sessions: tuple[date, ...] | None,
        observed: set[date],
        source_id: int | None,
        security_id: int | None,
        base_currency: str | None,
        quote_currency: str | None,
        at: datetime,
    ) -> list[DataAnomaly]:
        if sessions is None:
            return []
        return [
            self._anomaly(
                dataset,
                session,
                source_id,
                None,
                AnomalyType.MISSING_SESSION,
                AnomalySeverity.WARNING,
                "Expected trading session has no available observation.",
                at,
                security_id=security_id,
                base_currency=base_currency,
                quote_currency=quote_currency,
            )
            for session in sessions
            if session not in observed
        ]

    @staticmethod
    def _anomaly(
        dataset: DatasetType,
        observation_date: date,
        source_id: int | None,
        revision_number: int | None,
        kind: AnomalyType,
        severity: AnomalySeverity,
        explanation: str,
        detected_at: datetime,
        **kwargs: Any,
    ) -> DataAnomaly:
        return DataAnomaly(
            dataset_type=dataset,
            observation_date=observation_date,
            source_id=source_id,
            revision_number=revision_number,
            anomaly_type=kind,
            severity=severity,
            detection_rule=kind.value.lower(),
            detection_rule_version="1",
            detected_at=detected_at,
            explanation=explanation,
            **kwargs,
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError("as_of and detected_at must be timezone-aware.")
    return value.astimezone(UTC)
