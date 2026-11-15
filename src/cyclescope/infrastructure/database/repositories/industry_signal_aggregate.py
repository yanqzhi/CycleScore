"""SQLAlchemy persistence for immutable industry signal aggregate snapshots."""

from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from cyclescope.domain.entities.industry_signal import (
    IndustrySignalTemporalKind,
    IndustrySignalType,
    IndustrySignalUnit,
)
from cyclescope.domain.entities.industry_signal_aggregate import (
    AggregateInputRole,
    AggregateScopeRole,
    AggregateStatus,
    AggregationOperation,
    AggregationPolicyCode,
    IndustrySignalAggregateContributor,
    IndustrySignalAggregateScope,
    IndustrySignalAggregateSnapshot,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import IndustrySignalAggregateRepository
from cyclescope.infrastructure.database.models.industry_signal_aggregate import (
    IndustrySignalAggregateContributorModel,
    IndustrySignalAggregateModel,
    IndustrySignalAggregateScopeModel,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _to_contributor(
    row: IndustrySignalAggregateContributorModel,
) -> IndustrySignalAggregateContributor:
    return IndustrySignalAggregateContributor(
        observation_id=row.observation_id,
        source_id=row.source_id,
        revision_number=row.revision_number,
        region_code=row.region_code,
        observation_date=row.observation_date,
        period_start=row.period_start,
        period_end=row.period_end,
        publication_date=row.publication_date,
        publication_datetime=(
            _utc(row.publication_datetime) if row.publication_datetime else None
        ),
        available_at=_utc(row.available_at),
        collected_at=_utc(row.collected_at),
        source_reference=row.source_reference,
        role=AggregateInputRole(row.input_role),
        value=row.value,
        unit_code=IndustrySignalUnit(row.unit_code),
        currency_code=row.currency_code,
        classification_version_id=row.classification_version_id,
        classification_mapping_id=row.classification_mapping_id,
        included=row.included,
        calculation_weight=row.calculation_weight,
        exclusion_reason=row.exclusion_reason,
    )


def _to_snapshot(
    row: IndustrySignalAggregateModel,
    contributors: tuple[IndustrySignalAggregateContributor, ...],
    scopes: tuple[IndustrySignalAggregateScope, ...],
) -> IndustrySignalAggregateSnapshot:
    return IndustrySignalAggregateSnapshot(
        id=row.id,
        industry_id=row.industry_id,
        sub_industry_id=row.sub_industry_id,
        signal_type=IndustrySignalType(row.signal_type),
        temporal_kind=IndustrySignalTemporalKind(row.temporal_kind),
        aggregate_region_code=row.aggregate_region_code,
        aggregate_region_id=row.aggregate_region_id,
        requested_scopes=scopes,
        scope_complete=row.scope_complete,
        source_id=row.source_id,
        unit_code=IndustrySignalUnit(row.unit_code),
        currency_code=row.currency_code,
        observation_date=row.observation_date,
        period_start=row.period_start,
        period_end=row.period_end,
        as_of=_utc(row.as_of),
        calculated_at=_utc(row.calculated_at),
        policy_code=AggregationPolicyCode(row.policy_code),
        policy_version=row.policy_version,
        calculation_version=row.calculation_version,
        operation=AggregationOperation(row.operation),
        minimum_coverage=row.minimum_coverage,
        value=row.value,
        status=AggregateStatus(row.status),
        expected_contributor_count=row.expected_contributor_count,
        actual_contributor_count=row.actual_contributor_count,
        coverage_ratio=row.coverage_ratio,
        confidence=row.confidence,
        missing_reasons=tuple(row.missing_reasons),
        validation_warnings=tuple(row.validation_warnings),
        contributors=contributors,
    )


class SQLAlchemyIndustrySignalAggregateRepository(IndustrySignalAggregateRepository):
    """Append/read adapter; callers own commit and rollback."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, aggregate: IndustrySignalAggregateSnapshot
    ) -> IndustrySignalAggregateSnapshot:
        row = IndustrySignalAggregateModel(
            industry_id=aggregate.industry_id,
            sub_industry_id=aggregate.sub_industry_id,
            signal_type=aggregate.signal_type.value,
            temporal_kind=aggregate.temporal_kind.value,
            aggregate_region_code=aggregate.aggregate_region_code,
            aggregate_region_id=aggregate.aggregate_region_id,
            scope_complete=aggregate.scope_complete,
            source_id=aggregate.source_id,
            unit_code=aggregate.unit_code.value,
            currency_code=aggregate.currency_code,
            observation_date=aggregate.observation_date,
            period_start=aggregate.period_start,
            period_end=aggregate.period_end,
            as_of=aggregate.as_of.replace(tzinfo=None),
            calculated_at=aggregate.calculated_at.replace(tzinfo=None),
            policy_code=aggregate.policy_code.value,
            policy_version=aggregate.policy_version,
            calculation_version=aggregate.calculation_version,
            operation=aggregate.operation.value,
            minimum_coverage=aggregate.minimum_coverage,
            value=aggregate.value,
            status=aggregate.status.value,
            expected_contributor_count=aggregate.expected_contributor_count,
            actual_contributor_count=aggregate.actual_contributor_count,
            coverage_ratio=aggregate.coverage_ratio,
            confidence=aggregate.confidence,
            missing_reasons=list(aggregate.missing_reasons),
            validation_warnings=list(aggregate.validation_warnings),
        )
        self._session.add(row)
        self._session.flush()
        for scope in aggregate.requested_scopes:
            self._session.add(
                IndustrySignalAggregateScopeModel(
                    aggregate_id=row.id,
                    region_id=scope.region_id,
                    region_code=scope.region_code,
                    scope_role=scope.role.value,
                )
            )
        for contributor in aggregate.contributors:
            self._session.add(
                IndustrySignalAggregateContributorModel(
                    aggregate_id=row.id,
                    observation_id=contributor.observation_id,
                    source_id=contributor.source_id,
                    revision_number=contributor.revision_number,
                    region_code=contributor.region_code,
                    observation_date=contributor.observation_date,
                    period_start=contributor.period_start,
                    period_end=contributor.period_end,
                    publication_date=contributor.publication_date,
                    publication_datetime=(
                        contributor.publication_datetime.replace(tzinfo=None)
                        if contributor.publication_datetime
                        else None
                    ),
                    available_at=contributor.available_at.replace(tzinfo=None),
                    collected_at=contributor.collected_at.replace(tzinfo=None),
                    source_reference=contributor.source_reference,
                    input_role=contributor.role.value,
                    value=contributor.value,
                    unit_code=contributor.unit_code.value,
                    currency_code=contributor.currency_code,
                    classification_version_id=contributor.classification_version_id,
                    classification_mapping_id=contributor.classification_mapping_id,
                    included=contributor.included,
                    calculation_weight=contributor.calculation_weight,
                    exclusion_reason=contributor.exclusion_reason,
                )
            )
        self._session.flush()
        self._session.refresh(row)
        self._session.flush()
        return replace(aggregate, id=row.id)

    def get_by_id(self, aggregate_id: int) -> IndustrySignalAggregateSnapshot | None:
        row = self._session.get(IndustrySignalAggregateModel, aggregate_id)
        if row is None:
            return None
        return _to_snapshot(row, self._contributors(row.id), self._scopes(row.id))

    def list_by_industry(
        self,
        industry_id: int,
        *,
        signal_type: IndustrySignalType | None = None,
        as_of: datetime | None = None,
    ) -> list[IndustrySignalAggregateSnapshot]:
        query = select(IndustrySignalAggregateModel).where(
            IndustrySignalAggregateModel.industry_id == industry_id
        )
        if signal_type is not None:
            query = query.where(
                IndustrySignalAggregateModel.signal_type == signal_type.value
            )
        if as_of is not None:
            if as_of.tzinfo is None or as_of.utcoffset() is None:
                raise DomainValidationError("as_of must be timezone-aware.")
            query = query.where(
                IndustrySignalAggregateModel.as_of
                <= as_of.astimezone(UTC).replace(tzinfo=None)
            )
        rows = self._session.scalars(
            query.order_by(
                IndustrySignalAggregateModel.as_of,
                IndustrySignalAggregateModel.id,
            )
        )
        return [
            _to_snapshot(row, self._contributors(row.id), self._scopes(row.id))
            for row in rows
        ]

    def _scopes(self, aggregate_id: int) -> tuple[IndustrySignalAggregateScope, ...]:
        rows = self._session.scalars(
            select(IndustrySignalAggregateScopeModel)
            .where(IndustrySignalAggregateScopeModel.aggregate_id == aggregate_id)
            .order_by(
                IndustrySignalAggregateScopeModel.scope_role,
                IndustrySignalAggregateScopeModel.region_code,
                IndustrySignalAggregateScopeModel.region_id,
            )
        )
        return tuple(
            IndustrySignalAggregateScope(
                region_id=row.region_id,
                region_code=row.region_code,
                role=AggregateScopeRole(row.scope_role),
            )
            for row in rows
        )

    def _contributors(
        self, aggregate_id: int
    ) -> tuple[IndustrySignalAggregateContributor, ...]:
        rows = self._session.scalars(
            select(IndustrySignalAggregateContributorModel)
            .where(IndustrySignalAggregateContributorModel.aggregate_id == aggregate_id)
            .order_by(IndustrySignalAggregateContributorModel.id)
        )
        return tuple(_to_contributor(row) for row in rows)
