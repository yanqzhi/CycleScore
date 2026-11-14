"""Application workflows for calculating and reading valuation metrics."""

from datetime import UTC, date, datetime

from cyclescope.application.dto.valuation import (
    ValuationDateQuery,
    ValuationRangeQuery,
    ValuationSnapshotQuery,
    ValuationSnapshotResponse,
)
from cyclescope.domain.entities.valuation import (
    ValuationInputs,
    ValuationMetricCode,
    ValuationMetricValue,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    ValuationMetricRepository,
    ValuationMetricValueRepository,
)
from cyclescope.domain.services.valuation import calculate_metric


class CalculateValuationMetrics:
    """Calculate selected active definitions and persist immutable results.

    The caller owns the database transaction for the entire batch.
    Inputs must already have been assembled using PIT-aware market and financial
    access contracts; this workflow does not re-query or reinterpret source rows.
    """

    def __init__(
        self,
        definitions: ValuationMetricRepository,
        results: ValuationMetricValueRepository,
    ) -> None:
        self._definitions = definitions
        self._results = results

    def execute(
        self, inputs: ValuationInputs, metric_codes: tuple[ValuationMetricCode, ...]
    ) -> tuple[ValuationMetricValue, ...]:
        if not metric_codes or len(set(metric_codes)) != len(metric_codes):
            raise DomainValidationError(
                "metric_codes must be non-empty and must not contain duplicates."
            )
        stored: list[ValuationMetricValue] = []
        for code in metric_codes:
            definition = self._definitions.get_by_code(code)
            if definition is None or not definition.is_active:
                raise DomainValidationError(
                    f"Active metric definition {code} not found."
                )
            stored.append(self._results.create(calculate_metric(definition, inputs)))
        return tuple(stored)


class GetHistoricalValuationMetric:
    """Retrieve the latest stored calculation eligible at a requested cutoff."""

    def __init__(self, results: ValuationMetricValueRepository) -> None:
        self._results = results

    def execute(
        self,
        security_id: int,
        metric_code: ValuationMetricCode,
        observation_date: date,
        as_of: datetime,
    ) -> ValuationMetricValue | None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        if observation_date > as_of.astimezone(UTC).date():
            return None
        return self._results.get_as_of(
            security_id, metric_code, observation_date, as_of
        )


class GetValuationMetricsForDate:
    def __init__(self, results: ValuationMetricValueRepository) -> None:
        self._results = results

    def execute(self, request: ValuationDateQuery) -> ValuationSnapshotResponse:
        return ValuationSnapshotResponse(
            tuple(
                self._results.list_by_security(
                    request.security_id,
                    start_date=request.valuation_date,
                    end_date=request.valuation_date,
                    as_of=request.as_of,
                )
            )
        )


class GetHistoricalValuationMetrics:
    def __init__(self, results: ValuationMetricValueRepository) -> None:
        self._results = results

    def execute(self, request: ValuationRangeQuery) -> ValuationSnapshotResponse:
        return ValuationSnapshotResponse(
            tuple(
                self._results.list_by_security(
                    request.security_id,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    as_of=request.as_of,
                )
            )
        )


class GetValuationSnapshotsAsOf:
    def __init__(self, results: ValuationMetricValueRepository) -> None:
        self._results = results

    def execute(self, request: ValuationSnapshotQuery) -> ValuationSnapshotResponse:
        return ValuationSnapshotResponse(
            tuple(
                self._results.list_by_security(
                    request.security_id,
                    start_date=request.start_date,
                    end_date=request.end_date,
                    as_of=request.as_of,
                )
            )
        )


class GetValuationSnapshotProvenance:
    """Return the stored value object including every input reference."""

    def __init__(self, results: ValuationMetricValueRepository) -> None:
        self._results = results

    def execute(self, snapshot_id: int) -> ValuationMetricValue | None:
        if snapshot_id < 1:
            raise DomainValidationError("snapshot_id must be positive.")
        return self._results.get_by_id(snapshot_id)
