"""Application-owned market-data quality, calendar, and persistence ports."""

from abc import ABC, abstractmethod
from datetime import date
from typing import Protocol

from cyclescope.domain.entities.data_quality import DataAnomaly, DataQualityReport


class TradingCalendar(Protocol):
    """Exchange calendar port; implementations are deterministic and local."""

    def expected_sessions(
        self, calendar_id: str, start_date: date, end_date: date
    ) -> tuple[date, ...]: ...


class DataQualityRepository(ABC):
    @abstractmethod
    def persist_assessment(
        self, report: DataQualityReport, anomalies: tuple[DataAnomaly, ...]
    ) -> tuple[DataQualityReport, tuple[DataAnomaly, ...]]: ...

    @abstractmethod
    def get_report(self, report_id: int) -> DataQualityReport | None: ...

    @abstractmethod
    def get_anomaly(self, anomaly_id: int) -> DataAnomaly | None: ...

    @abstractmethod
    def update_anomaly(self, anomaly: DataAnomaly) -> DataAnomaly: ...

    @abstractmethod
    def list_anomalies(self, *, report_id: int | None = None) -> list[DataAnomaly]: ...
