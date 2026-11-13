"""Domain-owned CRUD repository contracts for master data."""

from abc import ABC, abstractmethod
from datetime import date, datetime

from cyclescope.domain.entities import Industry
from cyclescope.domain.entities.company import Company
from cyclescope.domain.entities.daily_price import DailyPrice
from cyclescope.domain.entities.data_source import DataSource
from cyclescope.domain.entities.fx_rate import FxRate
from cyclescope.domain.entities.security import Security
from cyclescope.domain.entities.sub_industry import SubIndustry
from cyclescope.domain.value_objects.market_data import CurrencyPair, MarketDataPeriod


class Repository[EntityT](ABC):
    """CRUD contract for an immutable domain entity."""

    @abstractmethod
    def create(self, entity: EntityT) -> EntityT:
        """Persist an entity and return it with its assigned identity."""

    @abstractmethod
    def get_by_id(self, entity_id: int) -> EntityT | None:
        """Return an entity by identifier, or ``None`` when it is absent."""

    @abstractmethod
    def list(self, *, limit: int = 100, offset: int = 0) -> list[EntityT]:
        """Return a page of entities."""

    @abstractmethod
    def update(self, entity: EntityT) -> EntityT | None:
        """Update an entity and return it, or ``None`` when it is absent."""

    @abstractmethod
    def delete(self, entity_id: int) -> bool:
        """Delete by identifier and report whether a row was removed."""


class IndustryRepository(Repository[Industry], ABC):
    """Industry persistence contract."""


class SubIndustryRepository(Repository[SubIndustry], ABC):
    """Sub-industry persistence contract."""


class CompanyRepository(Repository[Company], ABC):
    """Company persistence contract."""


class SecurityRepository(Repository[Security], ABC):
    """Security persistence contract."""


class DataSourceRepository(Repository[DataSource], ABC):
    """Data source persistence contract."""


class DailyPriceRepository(ABC):
    """Append-only repository for daily price revisions."""

    @abstractmethod
    def save(self, price: DailyPrice) -> bool:
        """Insert a new revision; return false if its unique key already exists."""

    @abstractmethod
    def get_by_security_and_period(
        self,
        security_id: int,
        period: MarketDataPeriod,
        as_of: datetime,
        source_id: int | None = None,
    ) -> list[DailyPrice]:
        """Return the latest available revision per source/date in date order."""

    @abstractmethod
    def get_latest_available(
        self, security_id: int, as_of: datetime, source_id: int | None = None
    ) -> DailyPrice | None:
        """Return the newest observation that was available by ``as_of``."""

    @abstractmethod
    def exists(
        self,
        security_id: int,
        observation_date: date,
        source_id: int,
        revision_number: int,
    ) -> bool:
        """Check the unique observation and revision key."""

    @abstractmethod
    def get_revisions(
        self, security_id: int, observation_date: date, source_id: int
    ) -> list[DailyPrice]:
        """Return every stored revision for one source/date in revision order."""


class FxRateRepository(ABC):
    """Append-only repository for FX rate revisions."""

    @abstractmethod
    def save(self, rate: FxRate) -> bool:
        """Insert a new revision; return false if its unique key already exists."""

    @abstractmethod
    def get_by_pair_and_period(
        self,
        pair: CurrencyPair,
        period: MarketDataPeriod,
        as_of: datetime,
        source_id: int | None = None,
    ) -> list[FxRate]:
        """Return latest available revisions per source/date in date order."""

    @abstractmethod
    def get_latest_available(
        self, pair: CurrencyPair, as_of: datetime, source_id: int | None = None
    ) -> FxRate | None:
        """Return the newest rate observation available by ``as_of``."""

    @abstractmethod
    def exists(
        self,
        pair: CurrencyPair,
        observation_date: date,
        source_id: int,
        revision_number: int,
    ) -> bool:
        """Check the unique pair/date/source/revision key."""

    @abstractmethod
    def get_revisions(
        self, pair: CurrencyPair, observation_date: date, source_id: int
    ) -> list[FxRate]:
        """Return every stored revision for one source/date in revision order."""
