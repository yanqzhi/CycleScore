"""Deterministic source-scoped point-in-time revision selection and comparison."""

from datetime import UTC, date, datetime
from decimal import Decimal

from cyclescope.application.dto.data_quality import RevisionComparison
from cyclescope.domain.entities import DailyPrice, FxRate
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    DailyPriceRepository,
    FxRateRepository,
)
from cyclescope.domain.value_objects.data_quality import DatasetType
from cyclescope.domain.value_objects.market_data import CurrencyPair


class MarketDataRevisionManagement:
    def __init__(
        self, price_repository: DailyPriceRepository, fx_repository: FxRateRepository
    ) -> None:
        self._prices = price_repository
        self._fx = fx_repository

    def price_revisions(
        self, security_id: int, observation_date: date, source_id: int
    ) -> tuple[DailyPrice, ...]:
        self._require_source(source_id)
        return tuple(
            self._prices.get_revisions(security_id, observation_date, source_id)
        )

    def fx_revisions(
        self, pair: CurrencyPair, observation_date: date, source_id: int
    ) -> tuple[FxRate, ...]:
        self._require_source(source_id)
        return tuple(self._fx.get_revisions(pair, observation_date, source_id))

    def price_as_of(
        self, security_id: int, observation_date: date, source_id: int, as_of: datetime
    ) -> DailyPrice | None:
        cutoff = _utc(as_of)
        if observation_date > cutoff.date():
            return None
        rows = self.price_revisions(security_id, observation_date, source_id)
        eligible = [row for row in rows if row.available_at <= cutoff]
        return max(
            eligible,
            key=lambda row: (row.revision_number, row.available_at, row.id or 0),
            default=None,
        )

    def fx_as_of(
        self,
        pair: CurrencyPair,
        observation_date: date,
        source_id: int,
        as_of: datetime,
    ) -> FxRate | None:
        cutoff = _utc(as_of)
        if observation_date > cutoff.date():
            return None
        rows = self.fx_revisions(pair, observation_date, source_id)
        eligible = [row for row in rows if row.available_at <= cutoff]
        return max(
            eligible,
            key=lambda row: (row.revision_number, row.available_at, row.id or 0),
            default=None,
        )

    def compare_prices(
        self, earlier: DailyPrice, later: DailyPrice
    ) -> RevisionComparison:
        if (earlier.security_id, earlier.observation_date, earlier.source_id) != (
            later.security_id,
            later.observation_date,
            later.source_id,
        ):
            raise DomainValidationError(
                "Price revisions must share a source-scoped observation key."
            )
        if later.revision_number <= earlier.revision_number:
            raise DomainValidationError(
                "Later price revision must have a higher revision number."
            )
        return RevisionComparison(
            DatasetType.DAILY_PRICE,
            earlier.observation_date,
            earlier.source_id,
            earlier.revision_number,
            later.revision_number,
            _changes(
                earlier,
                later,
                (
                    "open",
                    "high",
                    "low",
                    "close",
                    "adjusted_close",
                    "volume",
                    "currency",
                    "available_at",
                ),
            ),
            earlier.available_at,
            later.available_at,
            earlier.collected_at,
            later.collected_at,
        )

    def compare_fx(self, earlier: FxRate, later: FxRate) -> RevisionComparison:
        if (
            earlier.base_currency,
            earlier.quote_currency,
            earlier.observation_date,
            earlier.source_id,
        ) != (
            later.base_currency,
            later.quote_currency,
            later.observation_date,
            later.source_id,
        ):
            raise DomainValidationError(
                "FX revisions must share a source-scoped observation key."
            )
        if later.revision_number <= earlier.revision_number:
            raise DomainValidationError(
                "Later FX revision must have a higher revision number."
            )
        return RevisionComparison(
            DatasetType.FX_RATE,
            earlier.observation_date,
            earlier.source_id,
            earlier.revision_number,
            later.revision_number,
            _changes(earlier, later, ("rate", "publication_date", "available_at")),
            earlier.available_at,
            later.available_at,
            earlier.collected_at,
            later.collected_at,
        )

    @staticmethod
    def _require_source(source_id: int) -> None:
        if source_id < 1:
            raise DomainValidationError(
                "Revision lookup requires an explicit source_id."
            )


def _changes(
    earlier: DailyPrice | FxRate, later: DailyPrice | FxRate, fields: tuple[str, ...]
) -> tuple[
    tuple[
        str,
        Decimal | int | str | date | datetime | None,
        Decimal | int | str | date | datetime | None,
    ],
    ...,
]:
    return tuple(
        (name, getattr(earlier, name), getattr(later, name))
        for name in fields
        if getattr(earlier, name) != getattr(later, name)
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError("as_of must be timezone-aware.")
    return value.astimezone(UTC)
