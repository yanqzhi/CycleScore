"""Domain-owned CRUD repository contracts for master data."""

from abc import ABC, abstractmethod
from datetime import date, datetime

from cyclescope.domain.entities import Industry
from cyclescope.domain.entities.company import Company
from cyclescope.domain.entities.company_industry_exposure import CompanyIndustryExposure
from cyclescope.domain.entities.daily_price import DailyPrice
from cyclescope.domain.entities.data_source import DataSource
from cyclescope.domain.entities.exchange import Exchange
from cyclescope.domain.entities.financial_data import (
    FinancialItem,
    FinancialItemMapping,
    FinancialStatement,
    FinancialStatementItem,
)
from cyclescope.domain.entities.fx_rate import FxRate
from cyclescope.domain.entities.listing import Listing
from cyclescope.domain.entities.listing_status_event import ListingStatusEvent
from cyclescope.domain.entities.security import Security
from cyclescope.domain.entities.security_identifier import SecurityIdentifier
from cyclescope.domain.entities.sub_industry import SubIndustry
from cyclescope.domain.value_objects.financial_data import (
    ConsolidationScope,
    FiscalPeriod,
    StatementType,
)
from cyclescope.domain.value_objects.market_data import CurrencyPair, MarketDataPeriod
from cyclescope.domain.value_objects.security_identifier import (
    IdentifierUniquenessScope,
)


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


class ExchangeRepository(Repository[Exchange], ABC):
    """Exchange master persistence contract."""


class SecurityIdentifierRepository(Repository[SecurityIdentifier], ABC):
    """Security identifier persistence contract."""

    @abstractmethod
    def list_by_security(self, security_id: int) -> list[SecurityIdentifier]:
        """Return current and historical identifiers in effective-date order."""

    @abstractmethod
    def list_by_identifier(
        self,
        identifier_type: str,
        identifier_value: str,
        scope: IdentifierUniquenessScope,
    ) -> list[SecurityIdentifier]:
        """Return identifiers sharing a provider-neutral identifier scope."""


class ListingRepository(Repository[Listing], ABC):
    """Append-oriented exchange listing history persistence contract."""

    @abstractmethod
    def list_by_security(self, security_id: int) -> list[Listing]:
        """Return listing lifecycle records for one security."""

    @abstractmethod
    def list_by_exchange_ticker(self, exchange_id: int, ticker: str) -> list[Listing]:
        """Return lifecycle records for a ticker on one exchange."""


class ListingStatusEventRepository(ABC):
    """Append-only listing status history contract."""

    @abstractmethod
    def create(self, event: ListingStatusEvent) -> ListingStatusEvent:
        """Persist a status transition event."""

    @abstractmethod
    def list_by_listing(self, listing_id: int) -> list[ListingStatusEvent]:
        """Return chronological listing status transitions."""


class CompanyIndustryExposureRepository(Repository[CompanyIndustryExposure], ABC):
    """Company industry exposure persistence contract."""

    @abstractmethod
    def list_by_company(self, company_id: int) -> list[CompanyIndustryExposure]:
        """Return all effective and historical exposures for one company."""


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


class FinancialStatementRepository(ABC):
    """Append-only statements with source-specific as-of revisions."""

    @abstractmethod
    def create(self, entity: FinancialStatement) -> FinancialStatement: ...
    @abstractmethod
    def get_by_id(self, entity_id: int) -> FinancialStatement | None: ...
    @abstractmethod
    def list_by_company(self, company_id: int) -> list[FinancialStatement]: ...
    @abstractmethod
    def get_available_as_of(
        self,
        company_id: int,
        as_of: datetime,
        *,
        statement_type: StatementType | None = None,
        source_id: int | None = None,
    ) -> list[FinancialStatement]: ...
    @abstractmethod
    def get_revisions(
        self,
        company_id: int,
        source_id: int,
        statement_type: StatementType,
        period_start: date | None,
        period_end: date,
        accounting_standard: str,
        consolidation_scope: ConsolidationScope,
        fiscal_year: int,
        fiscal_period: FiscalPeriod,
    ) -> list[FinancialStatement]: ...
    @abstractmethod
    def exists_revision(self, entity: FinancialStatement) -> bool: ...


class FinancialItemRepository(ABC):
    @abstractmethod
    def create(self, entity: FinancialItem) -> FinancialItem: ...
    @abstractmethod
    def get_by_id(self, entity_id: int) -> FinancialItem | None: ...
    @abstractmethod
    def get_by_code(self, item_code: str) -> FinancialItem | None: ...
    @abstractmethod
    def list_by_statement_type(
        self, statement_type: StatementType
    ) -> list[FinancialItem]: ...


class FinancialStatementItemRepository(ABC):
    @abstractmethod
    def create(self, entity: FinancialStatementItem) -> FinancialStatementItem: ...
    @abstractmethod
    def list_by_statement(self, statement_id: int) -> list[FinancialStatementItem]: ...


class FinancialItemMappingRepository(ABC):
    @abstractmethod
    def create(self, entity: FinancialItemMapping) -> FinancialItemMapping: ...
    @abstractmethod
    def exists_mapping(
        self, source_id: int, source_item_code: str, accounting_standard: str | None
    ) -> bool: ...
    @abstractmethod
    def resolve_source_item(
        self,
        source_id: int,
        source_item_code: str,
        accounting_standard: str | None = None,
    ) -> FinancialItemMapping | None: ...
