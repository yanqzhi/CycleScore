"""Repository interfaces for master data."""

from abc import ABC, abstractmethod
from typing import TypeVar

T = TypeVar("T")


class ReadRepository[T](ABC):
    """Common read contract for a domain aggregate."""

    @abstractmethod
    def get_by_id(self, entity_id: int) -> T | None:
        """Return an entity by its identifier."""

    @abstractmethod
    def list(self, *, limit: int = 100, offset: int = 0) -> list[T]:
        """Return a page of entities."""


class IndustryRepository(ReadRepository[object], ABC):
    """Industry persistence contract."""


class SubIndustryRepository(ReadRepository[object], ABC):
    """Sub-industry persistence contract."""


class CompanyRepository(ReadRepository[object], ABC):
    """Company persistence contract."""


class SecurityRepository(ReadRepository[object], ABC):
    """Security persistence contract."""


class DataSourceRepository(ReadRepository[object], ABC):
    """Data source persistence contract."""
