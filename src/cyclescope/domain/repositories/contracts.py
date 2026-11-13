"""Domain-owned CRUD repository contracts for master data."""

from abc import ABC, abstractmethod

from cyclescope.domain.entities import Industry
from cyclescope.domain.entities.company import Company
from cyclescope.domain.entities.data_source import DataSource
from cyclescope.domain.entities.security import Security
from cyclescope.domain.entities.sub_industry import SubIndustry


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
