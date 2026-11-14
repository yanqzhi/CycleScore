"""SQLAlchemy adapters for valuation definitions and immutable results."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from cyclescope.domain.entities.valuation import (
    CurrencyApplicability,
    ValuationInputReference,
    ValuationMetricCode,
    ValuationMetricDefinition,
    ValuationMetricValue,
    ValuationResultStatus,
    ValuationUnit,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    ValuationMetricRepository,
    ValuationMetricValueRepository,
)
from cyclescope.infrastructure.database.models.valuation import (
    HistoricalValuationMetricModel,
    ValuationMetricModel,
    ValuationSnapshotInputModel,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _definition(row: ValuationMetricModel) -> ValuationMetricDefinition:
    return ValuationMetricDefinition(
        id=row.id,
        metric_code=ValuationMetricCode(row.metric_code),
        metric_name=row.metric_name,
        description=row.description,
        unit=ValuationUnit(row.unit),
        currency_applicability=CurrencyApplicability(row.currency_applicability),
        required_inputs=tuple(row.required_inputs),
        calculation_method=row.calculation_method,
        calculation_version=row.calculation_version,
        validity_rules=tuple(row.validity_rules),
        is_active=row.is_active,
    )


def _value(row: HistoricalValuationMetricModel) -> ValuationMetricValue:
    return ValuationMetricValue(
        id=row.id,
        security_id=row.security_id,
        metric_code=ValuationMetricCode(row.metric.metric_code),
        observation_date=row.observation_date,
        as_of=_utc(row.as_of),
        status=ValuationResultStatus(row.status),
        value=row.value,
        currency=row.currency,
        unit=ValuationUnit(row.unit),
        financial_period=row.financial_period,
        eps_calculation_method=row.eps_calculation_method,
        calculation_version=row.calculation_version,
        price_observation_id=row.price_observation_id,
        price_source_id=row.price_source_id,
        price_revision_number=row.price_revision_number,
        price_available_at=_utc(row.price_available_at)
        if row.price_available_at is not None
        else None,
        financial_statement_ids=tuple(row.financial_statement_ids),
        financial_source_ids=tuple(row.financial_source_ids),
        financial_statement_available_ats=tuple(
            datetime.fromisoformat(value)
            for value in row.financial_statement_available_ats
        ),
        input_snapshot=tuple(
            (name, Decimal(value)) for name, value in sorted(row.input_snapshot.items())
        ),
        input_references=tuple(
            ValuationInputReference(
                record_type=reference.record_type,
                record_id=(
                    reference.market_price_id
                    or reference.financial_statement_item_id
                    or 0
                ),
                parent_record_id=reference.financial_statement_id,
                source_id=reference.source_id,
                revision_number=reference.revision_number,
                available_at=_utc(reference.available_at),
                observation_date=reference.observation_date,
                financial_item_code=reference.financial_item_code,
                financial_period=reference.financial_period,
                period_start=reference.period_start,
                period_end=reference.period_end,
                publication_date=reference.publication_date,
                publication_datetime=_utc(reference.publication_datetime)
                if reference.publication_datetime is not None
                else None,
            )
            for reference in row.input_reference_rows
        ),
        unavailable_inputs=tuple(row.unavailable_inputs),
        unavailable_reason=row.unavailable_reason,
        created_at=_utc(row.created_at),
    )


class SQLAlchemyValuationMetricRepository(ValuationMetricRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, metric: ValuationMetricDefinition) -> ValuationMetricDefinition:
        row = ValuationMetricModel(
            metric_code=metric.metric_code.value,
            metric_name=metric.metric_name,
            description=metric.description,
            unit=metric.unit.value,
            currency_applicability=metric.currency_applicability.value,
            required_inputs=list(metric.required_inputs),
            calculation_method=metric.calculation_method,
            calculation_version=metric.calculation_version,
            validity_rules=list(metric.validity_rules),
            is_active=metric.is_active,
        )
        self.session.add(row)
        self.session.flush()
        return _definition(row)

    def get_by_code(
        self, metric_code: ValuationMetricCode
    ) -> ValuationMetricDefinition | None:
        row = self.session.scalar(
            select(ValuationMetricModel).where(
                ValuationMetricModel.metric_code == metric_code.value
            )
        )
        return _definition(row) if row else None

    def list_active(self) -> list[ValuationMetricDefinition]:
        rows = self.session.scalars(
            select(ValuationMetricModel)
            .where(ValuationMetricModel.is_active.is_(True))
            .order_by(ValuationMetricModel.metric_code)
        )
        return [_definition(row) for row in rows]


class SQLAlchemyValuationMetricValueRepository(ValuationMetricValueRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, value: ValuationMetricValue) -> ValuationMetricValue:
        metric = self.session.scalar(
            select(ValuationMetricModel).where(
                ValuationMetricModel.metric_code == value.metric_code.value
            )
        )
        if metric is None:
            raise DomainValidationError(
                f"Unknown valuation metric {value.metric_code.value}."
            )
        row = HistoricalValuationMetricModel(
            security_id=value.security_id,
            metric_id=metric.id,
            observation_date=value.observation_date,
            as_of=value.as_of,
            status=value.status.value,
            value=value.value,
            currency=value.currency,
            unit=value.unit.value,
            financial_period=value.financial_period,
            eps_calculation_method=value.eps_calculation_method,
            calculation_version=value.calculation_version,
            price_observation_id=value.price_observation_id,
            price_source_id=value.price_source_id,
            price_revision_number=value.price_revision_number,
            price_available_at=value.price_available_at,
            financial_statement_ids=list(value.financial_statement_ids),
            financial_source_ids=list(value.financial_source_ids),
            financial_statement_available_ats=[
                timestamp.isoformat()
                for timestamp in value.financial_statement_available_ats
            ],
            input_snapshot={name: str(number) for name, number in value.input_snapshot},
            unavailable_inputs=list(value.unavailable_inputs),
            unavailable_reason=value.unavailable_reason,
        )
        row.input_reference_rows = [
            ValuationSnapshotInputModel(
                record_type=reference.record_type,
                market_price_id=reference.record_id
                if reference.record_type == "DAILY_PRICE"
                else None,
                financial_statement_id=reference.parent_record_id,
                financial_statement_item_id=reference.record_id
                if reference.record_type == "FINANCIAL_LINE"
                else None,
                source_id=reference.source_id,
                revision_number=reference.revision_number,
                available_at=reference.available_at,
                observation_date=reference.observation_date,
                financial_item_code=reference.financial_item_code,
                financial_period=reference.financial_period,
                period_start=reference.period_start,
                period_end=reference.period_end,
                publication_date=reference.publication_date,
                publication_datetime=reference.publication_datetime,
            )
            for reference in value.input_references
        ]
        self.session.add(row)
        self.session.flush()
        return _value(row)

    def get_as_of(
        self,
        security_id: int,
        metric_code: ValuationMetricCode,
        observation_date: date,
        as_of: datetime,
    ) -> ValuationMetricValue | None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        row = self.session.scalar(
            select(HistoricalValuationMetricModel)
            .join(ValuationMetricModel)
            .where(
                HistoricalValuationMetricModel.security_id == security_id,
                ValuationMetricModel.metric_code == metric_code.value,
                HistoricalValuationMetricModel.observation_date == observation_date,
                HistoricalValuationMetricModel.as_of <= as_of.astimezone(UTC),
                HistoricalValuationMetricModel.observation_date
                <= as_of.astimezone(UTC).date(),
            )
            .order_by(
                HistoricalValuationMetricModel.as_of.desc(),
                HistoricalValuationMetricModel.id.desc(),
            )
            .limit(1)
        )
        return _value(row) if row else None

    def get_by_id(self, snapshot_id: int) -> ValuationMetricValue | None:
        row = self.session.get(HistoricalValuationMetricModel, snapshot_id)
        return _value(row) if row else None

    def list_by_security(
        self,
        security_id: int,
        metric_code: ValuationMetricCode | None = None,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        as_of: datetime | None = None,
    ) -> list[ValuationMetricValue]:
        query = (
            select(HistoricalValuationMetricModel)
            .join(ValuationMetricModel)
            .where(HistoricalValuationMetricModel.security_id == security_id)
        )
        if metric_code is not None:
            query = query.where(ValuationMetricModel.metric_code == metric_code.value)
        if start_date is not None:
            query = query.where(
                HistoricalValuationMetricModel.observation_date >= start_date
            )
        if end_date is not None:
            query = query.where(
                HistoricalValuationMetricModel.observation_date <= end_date
            )
        if as_of is not None:
            if as_of.tzinfo is None or as_of.utcoffset() is None:
                raise DomainValidationError("as_of must be timezone-aware.")
            query = query.where(
                HistoricalValuationMetricModel.as_of <= as_of.astimezone(UTC)
            )
            query = query.where(
                HistoricalValuationMetricModel.observation_date
                <= as_of.astimezone(UTC).date()
            )
        rows = self.session.scalars(
            query.order_by(
                HistoricalValuationMetricModel.observation_date,
                ValuationMetricModel.metric_code,
                HistoricalValuationMetricModel.as_of,
                HistoricalValuationMetricModel.id,
            )
        )
        return [_value(row) for row in rows]
