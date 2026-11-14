"""Persistence adapters for append-only price and FX observations."""

from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cyclescope.domain.entities import DailyPrice, FxRate
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    DailyPriceRepository,
    FxRateRepository,
)
from cyclescope.domain.value_objects.market_data import CurrencyPair, MarketDataPeriod
from cyclescope.infrastructure.database.models import DailyPriceModel, FxRateModel


def _as_utc(value: datetime) -> datetime:
    """Normalize aware timestamps and SQLite's naive timestamp reads to UTC."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _query_cutoff(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError("as_of must be timezone-aware.")
    return value.astimezone(UTC)


class SQLAlchemyDailyPriceRepository(DailyPriceRepository):
    """Append-only SQLAlchemy adapter for daily prices."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _to_entity(row: DailyPriceModel) -> DailyPrice:
        return DailyPrice(
            id=row.id,
            security_id=row.security_id,
            observation_date=row.observation_date,
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            adjusted_close=row.adjusted_close,
            volume=row.volume,
            currency=row.currency,
            source_id=row.source_id,
            publication_date=row.publication_date,
            available_at=_as_utc(row.available_at),
            collected_at=_as_utc(row.collected_at),
            revision_number=row.revision_number,
            created_at=_as_utc(row.created_at),
            updated_at=_as_utc(row.updated_at),
        )

    def exists(
        self,
        security_id: int,
        observation_date: date,
        source_id: int,
        revision_number: int,
    ) -> bool:
        statement = select(DailyPriceModel.id).where(
            DailyPriceModel.security_id == security_id,
            DailyPriceModel.observation_date == observation_date,
            DailyPriceModel.source_id == source_id,
            DailyPriceModel.revision_number == revision_number,
        )
        return self._session.scalar(statement) is not None

    def get_revisions(
        self, security_id: int, observation_date: date, source_id: int
    ) -> list[DailyPrice]:
        """Return all revisions for a source's security observation date."""
        rows = self._session.scalars(
            select(DailyPriceModel)
            .where(
                DailyPriceModel.security_id == security_id,
                DailyPriceModel.observation_date == observation_date,
                DailyPriceModel.source_id == source_id,
            )
            .order_by(
                DailyPriceModel.revision_number,
                DailyPriceModel.available_at,
                DailyPriceModel.id,
            )
        )
        return [self._to_entity(row) for row in rows]

    def save(self, price: DailyPrice) -> bool:
        """Insert a revision, preserving any row already stored at that key."""
        if self.exists(
            price.security_id,
            price.observation_date,
            price.source_id,
            price.revision_number,
        ):
            return False
        self._session.add(
            DailyPriceModel(
                security_id=price.security_id,
                observation_date=price.observation_date,
                open=price.open,
                high=price.high,
                low=price.low,
                close=price.close,
                adjusted_close=price.adjusted_close,
                volume=price.volume,
                currency=price.currency,
                source_id=price.source_id,
                publication_date=price.publication_date,
                available_at=price.available_at,
                collected_at=price.collected_at,
                revision_number=price.revision_number,
                created_at=price.created_at,
                updated_at=price.updated_at,
            )
        )
        self._session.flush()
        return True

    def get_by_security_and_period(
        self,
        security_id: int,
        period: MarketDataPeriod,
        as_of: datetime,
        source_id: int | None = None,
    ) -> list[DailyPrice]:
        """Return latest eligible revision per source/date in chronological order."""
        cutoff = _query_cutoff(as_of)
        conditions = [
            DailyPriceModel.security_id == security_id,
            DailyPriceModel.observation_date >= period.start_date,
            DailyPriceModel.observation_date <= min(period.end_date, cutoff.date()),
            DailyPriceModel.available_at <= cutoff,
        ]
        if source_id is not None:
            conditions.append(DailyPriceModel.source_id == source_id)
        ranked = (
            select(
                DailyPriceModel.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=(
                        DailyPriceModel.source_id,
                        DailyPriceModel.observation_date,
                    ),
                    order_by=(
                        DailyPriceModel.revision_number.desc(),
                        DailyPriceModel.available_at.desc(),
                        DailyPriceModel.id.desc(),
                    ),
                )
                .label("revision_rank"),
            )
            .where(*conditions)
            .subquery()
        )
        rows = self._session.scalars(
            select(DailyPriceModel)
            .join(ranked, DailyPriceModel.id == ranked.c.record_id)
            .where(ranked.c.revision_rank == 1)
            .order_by(DailyPriceModel.observation_date, DailyPriceModel.source_id)
        )
        return [self._to_entity(row) for row in rows]

    def get_preceding_by_security(
        self,
        security_id: int,
        start_date: date,
        as_of: datetime,
        source_id: int | None = None,
        *,
        limit_per_source: int = 20,
    ) -> list[DailyPrice]:
        if limit_per_source < 1:
            raise DomainValidationError("Lookback limit must be positive.")
        cutoff = _query_cutoff(as_of)
        conditions = [
            DailyPriceModel.security_id == security_id,
            DailyPriceModel.observation_date < start_date,
            DailyPriceModel.observation_date <= cutoff.date(),
            DailyPriceModel.available_at <= cutoff,
        ]
        if source_id is not None:
            conditions.append(DailyPriceModel.source_id == source_id)
        ranked_revisions = (
            select(
                DailyPriceModel.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=(
                        DailyPriceModel.source_id,
                        DailyPriceModel.observation_date,
                    ),
                    order_by=(
                        DailyPriceModel.revision_number.desc(),
                        DailyPriceModel.available_at.desc(),
                        DailyPriceModel.id.desc(),
                    ),
                )
                .label("revision_rank"),
            )
            .where(*conditions)
            .subquery()
        )
        latest_per_date = (
            select(
                ranked_revisions.c.record_id,
                DailyPriceModel.source_id.label("source_id"),
                DailyPriceModel.observation_date.label("observation_date"),
            )
            .join(
                DailyPriceModel,
                DailyPriceModel.id == ranked_revisions.c.record_id,
            )
            .where(ranked_revisions.c.revision_rank == 1)
            .subquery()
        )
        ranked_dates = select(
            latest_per_date.c.record_id,
            func.row_number()
            .over(
                partition_by=latest_per_date.c.source_id,
                order_by=latest_per_date.c.observation_date.desc(),
            )
            .label("lookback_rank"),
        ).subquery()
        record_ids = select(ranked_dates.c.record_id).where(
            ranked_dates.c.lookback_rank <= limit_per_source
        )
        rows = self._session.scalars(
            select(DailyPriceModel)
            .where(DailyPriceModel.id.in_(record_ids))
            .order_by(DailyPriceModel.observation_date, DailyPriceModel.source_id)
        )
        return [self._to_entity(row) for row in rows]

    def get_latest_available(
        self, security_id: int, as_of: datetime, source_id: int | None = None
    ) -> DailyPrice | None:
        """Return the newest eligible observation, excluding future market dates."""
        candidates = self.get_latest_by_source(security_id, as_of, source_id)
        return max(
            candidates,
            key=lambda row: (
                row.observation_date,
                row.available_at,
                row.revision_number,
                -row.source_id,
            ),
            default=None,
        )

    def get_latest_by_source(
        self, security_id: int, as_of: datetime, source_id: int | None = None
    ) -> list[DailyPrice]:
        cutoff = _query_cutoff(as_of)
        conditions = [
            DailyPriceModel.security_id == security_id,
            DailyPriceModel.observation_date <= cutoff.date(),
            DailyPriceModel.available_at <= cutoff,
        ]
        if source_id is not None:
            conditions.append(DailyPriceModel.source_id == source_id)
        ranked = (
            select(
                DailyPriceModel.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=DailyPriceModel.source_id,
                    order_by=(
                        DailyPriceModel.observation_date.desc(),
                        DailyPriceModel.revision_number.desc(),
                        DailyPriceModel.available_at.desc(),
                        DailyPriceModel.id.desc(),
                    ),
                )
                .label("source_rank"),
            )
            .where(*conditions)
            .subquery()
        )
        rows = self._session.scalars(
            select(DailyPriceModel)
            .join(ranked, DailyPriceModel.id == ranked.c.record_id)
            .where(ranked.c.source_rank == 1)
            .order_by(DailyPriceModel.source_id)
        )
        return [self._to_entity(row) for row in rows]


class SQLAlchemyFxRateRepository(FxRateRepository):
    """Append-only SQLAlchemy adapter for FX rates."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _to_entity(row: FxRateModel) -> FxRate:
        return FxRate(
            id=row.id,
            base_currency=row.base_currency,
            quote_currency=row.quote_currency,
            observation_date=row.observation_date,
            rate=row.rate,
            source_id=row.source_id,
            publication_date=row.publication_date,
            available_at=_as_utc(row.available_at),
            collected_at=_as_utc(row.collected_at),
            revision_number=row.revision_number,
            created_at=_as_utc(row.created_at),
            updated_at=_as_utc(row.updated_at),
        )

    def exists(
        self,
        pair: CurrencyPair,
        observation_date: date,
        source_id: int,
        revision_number: int,
    ) -> bool:
        statement = select(FxRateModel.id).where(
            FxRateModel.base_currency == pair.base_currency,
            FxRateModel.quote_currency == pair.quote_currency,
            FxRateModel.observation_date == observation_date,
            FxRateModel.source_id == source_id,
            FxRateModel.revision_number == revision_number,
        )
        return self._session.scalar(statement) is not None

    def get_revisions(
        self, pair: CurrencyPair, observation_date: date, source_id: int
    ) -> list[FxRate]:
        """Return all revisions for a source's FX observation date."""
        rows = self._session.scalars(
            select(FxRateModel)
            .where(
                FxRateModel.base_currency == pair.base_currency,
                FxRateModel.quote_currency == pair.quote_currency,
                FxRateModel.observation_date == observation_date,
                FxRateModel.source_id == source_id,
            )
            .order_by(
                FxRateModel.revision_number,
                FxRateModel.available_at,
                FxRateModel.id,
            )
        )
        return [self._to_entity(row) for row in rows]

    def save(self, rate: FxRate) -> bool:
        """Insert a revision, preserving any row already stored at that key."""
        pair = CurrencyPair(rate.base_currency, rate.quote_currency)
        if self.exists(
            pair, rate.observation_date, rate.source_id, rate.revision_number
        ):
            return False
        self._session.add(
            FxRateModel(
                base_currency=rate.base_currency,
                quote_currency=rate.quote_currency,
                observation_date=rate.observation_date,
                rate=rate.rate,
                source_id=rate.source_id,
                publication_date=rate.publication_date,
                available_at=rate.available_at,
                collected_at=rate.collected_at,
                revision_number=rate.revision_number,
                created_at=rate.created_at,
                updated_at=rate.updated_at,
            )
        )
        self._session.flush()
        return True

    def get_by_pair_and_period(
        self,
        pair: CurrencyPair,
        period: MarketDataPeriod,
        as_of: datetime,
        source_id: int | None = None,
    ) -> list[FxRate]:
        """Return latest eligible revision per source/date in chronological order."""
        cutoff = _query_cutoff(as_of)
        conditions = [
            FxRateModel.base_currency == pair.base_currency,
            FxRateModel.quote_currency == pair.quote_currency,
            FxRateModel.observation_date >= period.start_date,
            FxRateModel.observation_date <= min(period.end_date, cutoff.date()),
            FxRateModel.available_at <= cutoff,
        ]
        if source_id is not None:
            conditions.append(FxRateModel.source_id == source_id)
        ranked = (
            select(
                FxRateModel.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=(
                        FxRateModel.source_id,
                        FxRateModel.observation_date,
                    ),
                    order_by=(
                        FxRateModel.revision_number.desc(),
                        FxRateModel.available_at.desc(),
                        FxRateModel.id.desc(),
                    ),
                )
                .label("revision_rank"),
            )
            .where(*conditions)
            .subquery()
        )
        rows = self._session.scalars(
            select(FxRateModel)
            .join(ranked, FxRateModel.id == ranked.c.record_id)
            .where(ranked.c.revision_rank == 1)
            .order_by(FxRateModel.observation_date, FxRateModel.source_id)
        )
        return [self._to_entity(row) for row in rows]

    def get_preceding_by_pair(
        self,
        pair: CurrencyPair,
        start_date: date,
        as_of: datetime,
        source_id: int | None = None,
        *,
        limit_per_source: int = 20,
    ) -> list[FxRate]:
        if limit_per_source < 1:
            raise DomainValidationError("Lookback limit must be positive.")
        cutoff = _query_cutoff(as_of)
        conditions = [
            FxRateModel.base_currency == pair.base_currency,
            FxRateModel.quote_currency == pair.quote_currency,
            FxRateModel.observation_date < start_date,
            FxRateModel.observation_date <= cutoff.date(),
            FxRateModel.available_at <= cutoff,
        ]
        if source_id is not None:
            conditions.append(FxRateModel.source_id == source_id)
        ranked_revisions = (
            select(
                FxRateModel.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=(
                        FxRateModel.source_id,
                        FxRateModel.observation_date,
                    ),
                    order_by=(
                        FxRateModel.revision_number.desc(),
                        FxRateModel.available_at.desc(),
                        FxRateModel.id.desc(),
                    ),
                )
                .label("revision_rank"),
            )
            .where(*conditions)
            .subquery()
        )
        latest_per_date = (
            select(
                ranked_revisions.c.record_id,
                FxRateModel.source_id.label("source_id"),
                FxRateModel.observation_date.label("observation_date"),
            )
            .join(FxRateModel, FxRateModel.id == ranked_revisions.c.record_id)
            .where(ranked_revisions.c.revision_rank == 1)
            .subquery()
        )
        ranked_dates = select(
            latest_per_date.c.record_id,
            func.row_number()
            .over(
                partition_by=latest_per_date.c.source_id,
                order_by=latest_per_date.c.observation_date.desc(),
            )
            .label("lookback_rank"),
        ).subquery()
        record_ids = select(ranked_dates.c.record_id).where(
            ranked_dates.c.lookback_rank <= limit_per_source
        )
        rows = self._session.scalars(
            select(FxRateModel)
            .where(FxRateModel.id.in_(record_ids))
            .order_by(
                FxRateModel.observation_date,
                FxRateModel.source_id,
            )
        )
        return [self._to_entity(row) for row in rows]

    def get_latest_available(
        self, pair: CurrencyPair, as_of: datetime, source_id: int | None = None
    ) -> FxRate | None:
        """Return the newest eligible rate, excluding future observation dates."""
        candidates = self.get_latest_by_source(pair, as_of, source_id)
        return max(
            candidates,
            key=lambda row: (
                row.observation_date,
                row.available_at,
                row.revision_number,
                -row.source_id,
            ),
            default=None,
        )

    def get_latest_by_source(
        self, pair: CurrencyPair, as_of: datetime, source_id: int | None = None
    ) -> list[FxRate]:
        cutoff = _query_cutoff(as_of)
        conditions = [
            FxRateModel.base_currency == pair.base_currency,
            FxRateModel.quote_currency == pair.quote_currency,
            FxRateModel.observation_date <= cutoff.date(),
            FxRateModel.available_at <= cutoff,
        ]
        if source_id is not None:
            conditions.append(FxRateModel.source_id == source_id)
        ranked = (
            select(
                FxRateModel.id.label("record_id"),
                func.row_number()
                .over(
                    partition_by=FxRateModel.source_id,
                    order_by=(
                        FxRateModel.observation_date.desc(),
                        FxRateModel.revision_number.desc(),
                        FxRateModel.available_at.desc(),
                        FxRateModel.id.desc(),
                    ),
                )
                .label("source_rank"),
            )
            .where(*conditions)
            .subquery()
        )
        rows = self._session.scalars(
            select(FxRateModel)
            .join(ranked, FxRateModel.id == ranked.c.record_id)
            .where(ranked.c.source_rank == 1)
            .order_by(FxRateModel.source_id)
        )
        return [self._to_entity(row) for row in rows]
