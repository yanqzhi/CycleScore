"""SQLAlchemy persistence adapter for append-only percentile snapshots."""

from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from cyclescope.domain.entities.valuation_percentile import (
    PercentileConfidence,
    PercentileMethod,
    PercentileMetric,
    PercentileObservationAudit,
    ValuationLookbackPeriod,
    ValuationPercentileResult,
    ValuationPercentileStatus,
)
from cyclescope.domain.repositories.contracts import ValuationPercentileRepository
from cyclescope.infrastructure.database.models.valuation import (
    HistoricalValuationMetricModel,
)
from cyclescope.infrastructure.database.models.valuation_percentile import (
    ValuationPercentileInputModel,
    ValuationPercentileResultModel,
)
from cyclescope.infrastructure.database.repositories.normalized_earnings import (
    _to_domain as _normalized_domain,
)
from cyclescope.infrastructure.database.repositories.valuation import (
    _value as _valuation_value,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _domain(row: ValuationPercentileResultModel) -> ValuationPercentileResult:
    observations = []
    for item in row.input_rows:
        reference_sets = []
        if item.valuation_snapshot is not None:
            reference_sets.append(
                _valuation_value(item.valuation_snapshot).input_references
            )
        if item.normalized_earnings_result is not None:
            reference_sets.append(
                _normalized_domain(
                    item.normalized_earnings_result
                ).valuation_input_references
            )
        references = tuple(
            dict.fromkeys(ref for group in reference_sets for ref in group)
        )
        observations.append(
            PercentileObservationAudit(
                observation_date=item.observation_date,
                value=item.value,
                included=item.included,
                reason=item.reason,
                snapshot_id=item.valuation_snapshot_id,
                normalized_earnings_result_id=item.normalized_earnings_result_id,
                market_source_id=item.market_source_id,
                financial_source_ids=tuple(item.financial_source_ids),
                references=references,
            )
        )
    return ValuationPercentileResult(
        id=row.id,
        security_id=row.security_id,
        company_id=row.company_id,
        metric=PercentileMetric(row.metric),
        lookback_period=ValuationLookbackPeriod(row.lookback_period),
        method=PercentileMethod(row.method),
        as_of=_utc(row.as_of),
        observation_start=row.observation_start,
        observation_end=row.observation_end,
        current_value=row.current_value,
        percentile=row.percentile,
        historical_minimum=row.historical_minimum,
        historical_maximum=row.historical_maximum,
        historical_median=row.historical_median,
        valid_observations=row.valid_observations,
        excluded_observations=row.excluded_observations,
        expected_observations=row.expected_observations,
        coverage_ratio=row.coverage_ratio,
        status=ValuationPercentileStatus(row.status),
        confidence=PercentileConfidence(row.confidence),
        data_quality=row.data_quality,
        currency=row.currency,
        unit=row.unit,
        financial_period=row.financial_period,
        calculation_version=row.calculation_version,
        status_reason=row.status_reason,
        observations=tuple(observations),
        created_at=_utc(row.created_at),
    )


class SQLAlchemyValuationPercentileRepository(ValuationPercentileRepository):
    """Append results and audit inputs; the caller owns transactions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, result: ValuationPercentileResult) -> ValuationPercentileResult:
        row = ValuationPercentileResultModel(
            security_id=result.security_id,
            company_id=result.company_id,
            metric=result.metric.value,
            lookback_period=result.lookback_period.value,
            method=result.method.value,
            as_of=result.as_of,
            observation_start=result.observation_start,
            observation_end=result.observation_end,
            current_value=result.current_value,
            percentile=result.percentile,
            historical_minimum=result.historical_minimum,
            historical_maximum=result.historical_maximum,
            historical_median=result.historical_median,
            valid_observations=result.valid_observations,
            excluded_observations=result.excluded_observations,
            expected_observations=result.expected_observations,
            coverage_ratio=result.coverage_ratio,
            status=result.status.value,
            confidence=result.confidence.value,
            data_quality=result.data_quality,
            currency=result.currency,
            unit=result.unit,
            financial_period=result.financial_period,
            calculation_version=result.calculation_version,
            status_reason=result.status_reason,
        )
        row.input_rows = [
            ValuationPercentileInputModel(
                observation_date=item.observation_date,
                value=item.value,
                included=item.included,
                reason=item.reason,
                valuation_snapshot_id=item.snapshot_id,
                normalized_earnings_result_id=item.normalized_earnings_result_id,
                market_source_id=item.market_source_id,
                financial_source_ids=list(item.financial_source_ids),
            )
            for item in result.observations
        ]
        self.session.add(row)
        self.session.flush()
        return replace(
            result,
            id=row.id,
            created_at=_utc(row.created_at),
        )

    def get_by_id(self, result_id: int) -> ValuationPercentileResult | None:
        row = self.session.scalar(
            select(ValuationPercentileResultModel)
            .options(
                selectinload(ValuationPercentileResultModel.input_rows)
                .joinedload(ValuationPercentileInputModel.valuation_snapshot)
                .joinedload(HistoricalValuationMetricModel.metric),
                selectinload(ValuationPercentileResultModel.input_rows)
                .joinedload(ValuationPercentileInputModel.valuation_snapshot)
                .selectinload(HistoricalValuationMetricModel.input_reference_rows),
                selectinload(ValuationPercentileResultModel.input_rows).joinedload(
                    ValuationPercentileInputModel.normalized_earnings_result
                ),
            )
            .where(ValuationPercentileResultModel.id == result_id)
        )
        return _domain(row) if row is not None else None

    def list_by_security(
        self, security_id: int, *, as_of: datetime | None = None
    ) -> list[ValuationPercentileResult]:
        query = select(ValuationPercentileResultModel).where(
            ValuationPercentileResultModel.security_id == security_id
        )
        query = query.options(
            selectinload(ValuationPercentileResultModel.input_rows)
            .joinedload(ValuationPercentileInputModel.valuation_snapshot)
            .joinedload(HistoricalValuationMetricModel.metric),
            selectinload(ValuationPercentileResultModel.input_rows)
            .joinedload(ValuationPercentileInputModel.valuation_snapshot)
            .selectinload(HistoricalValuationMetricModel.input_reference_rows),
            selectinload(ValuationPercentileResultModel.input_rows).joinedload(
                ValuationPercentileInputModel.normalized_earnings_result
            ),
        )
        if as_of is not None:
            if as_of.tzinfo is None or as_of.utcoffset() is None:
                from cyclescope.domain.exceptions import DomainValidationError

                raise DomainValidationError("as_of must be timezone-aware.")
            query = query.where(
                ValuationPercentileResultModel.as_of <= as_of.astimezone(UTC)
            )
        rows = self.session.scalars(
            query.order_by(
                ValuationPercentileResultModel.as_of,
                ValuationPercentileResultModel.id,
            )
        )
        return [_domain(row) for row in rows]
