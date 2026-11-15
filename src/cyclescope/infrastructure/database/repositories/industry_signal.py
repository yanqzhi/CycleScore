"""SQLAlchemy persistence for append-only industry signal revisions."""

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from cyclescope.domain.entities.industry_signal import (
    IndustrySignalObservation,
    IndustrySignalTemporalKind,
    IndustrySignalType,
    IndustrySignalUnit,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    IndustrySignalObservationRepository,
)
from cyclescope.infrastructure.database.models.industry_signal import (
    IndustrySignalObservationModel,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _to_domain(row: IndustrySignalObservationModel) -> IndustrySignalObservation:
    return IndustrySignalObservation(
        id=row.id,
        industry_id=row.industry_id,
        sub_industry_id=row.sub_industry_id,
        source_id=row.source_id,
        signal_type=IndustrySignalType(row.signal_type),
        region_code=row.region_code,
        observation_date=row.observation_date,
        period_start=row.period_start,
        period_end=row.period_end,
        value=row.value,
        unit_code=IndustrySignalUnit(row.unit_code),
        currency_code=row.currency_code,
        publication_date=row.publication_date,
        publication_datetime=(
            _utc(row.publication_datetime) if row.publication_datetime else None
        ),
        available_at=_utc(row.available_at),
        collected_at=_utc(row.collected_at),
        revision_number=row.revision_number,
        source_reference=row.source_reference,
        missing_reason=row.missing_reason,
        created_at=_utc(row.created_at),
    )


class SQLAlchemyIndustrySignalObservationRepository(
    IndustrySignalObservationRepository
):
    """Append-only industry signals; transaction control belongs to callers."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, observation: IndustrySignalObservation
    ) -> IndustrySignalObservation:
        if self.exists_revision(observation):
            raise DomainValidationError("Industry signal revision already exists.")
        row = IndustrySignalObservationModel(
            industry_id=observation.industry_id,
            sub_industry_id=observation.sub_industry_id,
            source_id=observation.source_id,
            signal_type=observation.signal_type.value,
            temporal_kind=observation.temporal_kind.value,
            region_code=observation.region_code,
            observation_date=observation.observation_date,
            period_start=observation.period_start,
            period_end=observation.period_end,
            value=observation.value,
            unit_code=observation.unit_code.value,
            currency_code=observation.currency_code,
            publication_date=observation.publication_date,
            publication_datetime=(
                observation.publication_datetime.replace(tzinfo=None)
                if observation.publication_datetime
                else None
            ),
            available_at=observation.available_at.replace(tzinfo=None),
            collected_at=observation.collected_at.replace(tzinfo=None),
            revision_number=observation.revision_number,
            source_reference=observation.source_reference,
            missing_reason=observation.missing_reason,
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _to_domain(row)

    def exists_revision(self, observation: IndustrySignalObservation) -> bool:
        query = select(IndustrySignalObservationModel.id).where(
            IndustrySignalObservationModel.industry_id == observation.industry_id,
            IndustrySignalObservationModel.sub_industry_id
            == observation.sub_industry_id,
            IndustrySignalObservationModel.source_id == observation.source_id,
            IndustrySignalObservationModel.signal_type == observation.signal_type.value,
            IndustrySignalObservationModel.temporal_kind
            == observation.temporal_kind.value,
            IndustrySignalObservationModel.region_code == observation.region_code,
            IndustrySignalObservationModel.observation_date
            == observation.observation_date,
            IndustrySignalObservationModel.period_start == observation.period_start,
            IndustrySignalObservationModel.period_end == observation.period_end,
            IndustrySignalObservationModel.revision_number
            == observation.revision_number,
        )
        return self._session.scalar(query) is not None

    def list_available_as_of(
        self,
        industry_id: int,
        as_of: datetime,
        *,
        signal_type: IndustrySignalType | None = None,
        sub_industry_id: int | None = None,
        region_code: str | None = None,
        source_id: int | None = None,
    ) -> list[IndustrySignalObservation]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        cutoff = as_of.astimezone(UTC)
        observation_cutoff = cutoff.date()
        query = select(IndustrySignalObservationModel).where(
            IndustrySignalObservationModel.industry_id == industry_id,
            IndustrySignalObservationModel.available_at <= cutoff.replace(tzinfo=None),
            or_(
                and_(
                    IndustrySignalObservationModel.temporal_kind
                    == IndustrySignalTemporalKind.PERIOD.value,
                    IndustrySignalObservationModel.period_end <= observation_cutoff,
                ),
                and_(
                    IndustrySignalObservationModel.temporal_kind
                    != IndustrySignalTemporalKind.PERIOD.value,
                    IndustrySignalObservationModel.observation_date
                    <= observation_cutoff,
                ),
            ),
        )
        if signal_type is not None:
            query = query.where(
                IndustrySignalObservationModel.signal_type == signal_type.value
            )
        if sub_industry_id is not None:
            query = query.where(
                IndustrySignalObservationModel.sub_industry_id.is_(sub_industry_id)
            )
        if region_code is not None:
            query = query.where(
                IndustrySignalObservationModel.region_code == region_code
            )
        if source_id is not None:
            query = query.where(IndustrySignalObservationModel.source_id == source_id)
        rows = self._session.scalars(
            query.order_by(
                IndustrySignalObservationModel.source_id,
                IndustrySignalObservationModel.signal_type,
                IndustrySignalObservationModel.observation_date,
                IndustrySignalObservationModel.period_end,
                IndustrySignalObservationModel.revision_number,
                IndustrySignalObservationModel.id,
            )
        )
        return [_to_domain(row) for row in rows]
