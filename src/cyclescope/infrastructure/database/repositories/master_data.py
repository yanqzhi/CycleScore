"""Repository adapters for SQLAlchemy master-data models."""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase, Session

from cyclescope.domain.repositories.contracts import (
    CompanyRepository,
    DataSourceRepository,
    IndustryRepository,
    SecurityRepository,
    SubIndustryRepository,
)
from cyclescope.infrastructure.database.models import (
    CompanyModel,
    DataSourceModel,
    IndustryModel,
    SecurityModel,
    SubIndustryModel,
)


class SqlAlchemyRepository[M: DeclarativeBase]:
    """Small CRUD adapter that returns detached value dictionaries, not ORM rows."""

    def __init__(self, session: Session, model: type[M]) -> None:
        self._session = session
        self._model = model

    @staticmethod
    def _values(row: DeclarativeBase) -> dict[str, Any]:
        """Copy mapped scalar columns into a persistence-neutral dictionary."""
        mapper = row.__mapper__
        values = {column.key: getattr(row, column.key) for column in mapper.columns}
        for key, value in values.items():
            if isinstance(value, datetime) and value.tzinfo is None:
                values[key] = value.replace(tzinfo=UTC)
        return values

    def create(self, values: Mapping[str, object]) -> dict[str, Any]:
        """Create a row and return its scalar values."""
        row = self._model(**values)
        self._session.add(row)
        self._session.flush()
        return self._values(row)

    def get_by_id(self, entity_id: int) -> dict[str, Any] | None:
        """Find a row by primary key."""
        row = self._session.get(self._model, entity_id)
        return None if row is None else self._values(row)

    def list(self, *, limit: int = 100, offset: int = 0) -> list[object]:
        """Return an ordered page of scalar records."""
        if limit < 1 or offset < 0:
            raise ValueError("limit must be positive and offset must not be negative")
        primary_key = self._model.__mapper__.primary_key[0]
        rows = self._session.scalars(
            select(self._model).order_by(primary_key).limit(limit).offset(offset)
        )
        return [self._values(row) for row in rows]

    def update(
        self, entity_id: int, values: Mapping[str, object]
    ) -> dict[str, Any] | None:
        """Update an existing row and return its scalar values."""
        row = self._session.get(self._model, entity_id)
        if row is None:
            return None
        for key, value in values.items():
            if key != "id" and hasattr(row, key):
                setattr(row, key, value)
        self._session.flush()
        return self._values(row)

    def delete(self, entity_id: int) -> bool:
        """Delete a row by ID; foreign-key rules protect referenced master data."""
        row = self._session.get(self._model, entity_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True


class IndustrySqlAlchemyRepository(
    SqlAlchemyRepository[IndustryModel], IndustryRepository
):
    """Industry repository adapter."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, IndustryModel)


class SubIndustrySqlAlchemyRepository(
    SqlAlchemyRepository[SubIndustryModel], SubIndustryRepository
):
    """Sub-industry repository adapter."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, SubIndustryModel)


class CompanySqlAlchemyRepository(
    SqlAlchemyRepository[CompanyModel], CompanyRepository
):
    """Company repository adapter."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, CompanyModel)


class SecuritySqlAlchemyRepository(
    SqlAlchemyRepository[SecurityModel], SecurityRepository
):
    """Security repository adapter."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, SecurityModel)


class DataSourceSqlAlchemyRepository(
    SqlAlchemyRepository[DataSourceModel], DataSourceRepository
):
    """Data-source repository adapter."""

    def __init__(self, session: Session) -> None:
        super().__init__(session, DataSourceModel)
