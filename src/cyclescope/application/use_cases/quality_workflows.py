"""Application orchestration for quality reports and anomaly lifecycle."""

from datetime import UTC, datetime

from cyclescope.application.dto.data_quality import (
    FxQualityRequest,
    PriceQualityRequest,
    QualityAssessmentResult,
)
from cyclescope.application.interfaces.data_quality import (
    DataQualityRepository,
    TradingCalendar,
)
from cyclescope.application.use_cases.market_data_quality import (
    MarketDataQualityAssessor,
)
from cyclescope.domain.entities.data_quality import DataAnomaly
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    DailyPriceRepository,
    FxRateRepository,
)
from cyclescope.domain.value_objects.data_quality import (
    AnomalyStatus,
    DataQualityConfig,
)
from cyclescope.domain.value_objects.market_data import CurrencyPair, MarketDataPeriod


class AssessDailyPriceQuality:
    def __init__(
        self,
        market_repository: DailyPriceRepository,
        quality_repository: DataQualityRepository,
        calendar: TradingCalendar | None,
        config: DataQualityConfig | None = None,
    ) -> None:
        self._market = market_repository
        self._quality = quality_repository
        self._calendar = calendar
        self._assessor = MarketDataQualityAssessor(config)

    def execute(self, request: PriceQualityRequest) -> QualityAssessmentResult:
        period = MarketDataPeriod(request.start_date, request.end_date)
        records = self._market.get_by_security_and_period(
            request.security_id, period, request.as_of, request.source_id
        )
        assessment = self._assessor.assess_prices(request, records, self._calendar)
        report, anomalies = self._quality.persist_assessment(
            assessment.report, assessment.anomalies
        )
        return QualityAssessmentResult(report, anomalies)


class AssessFxRateQuality:
    def __init__(
        self,
        market_repository: FxRateRepository,
        quality_repository: DataQualityRepository,
        calendar: TradingCalendar | None,
        config: DataQualityConfig | None = None,
    ) -> None:
        self._market = market_repository
        self._quality = quality_repository
        self._calendar = calendar
        self._assessor = MarketDataQualityAssessor(config)

    def execute(self, request: FxQualityRequest) -> QualityAssessmentResult:
        pair = CurrencyPair(request.base_currency, request.quote_currency)
        period = MarketDataPeriod(request.start_date, request.end_date)
        records = self._market.get_by_pair_and_period(
            pair, period, request.as_of, request.source_id
        )
        assessment = self._assessor.assess_fx(request, records, self._calendar)
        report, anomalies = self._quality.persist_assessment(
            assessment.report, assessment.anomalies
        )
        return QualityAssessmentResult(report, anomalies)


class ManageMarketDataAnomaly:
    def __init__(self, repository: DataQualityRepository) -> None:
        self._repository = repository

    def transition(
        self, anomaly_id: int, status: AnomalyStatus, at: datetime
    ) -> DataAnomaly:
        if at.tzinfo is None or at.utcoffset() is None:
            raise DomainValidationError(
                "Anomaly transition time must be timezone-aware."
            )
        current = self._repository.get_anomaly(anomaly_id)
        if current is None:
            raise DomainValidationError("Anomaly does not exist.")
        return self._repository.update_anomaly(
            current.transition(status, at.astimezone(UTC))
        )
