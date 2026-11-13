"""SQLAlchemy adapters that translate rows to domain entities."""

from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase, Session

from cyclescope.domain.entities import (
    Company,
    DataSource,
    Industry,
    Security,
    SubIndustry,
)
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


class SqlAlchemyRepository[M: DeclarativeBase, EntityT]:
    """CRUD adapter with explicit persistence-to-domain mapping."""

    def __init__(
        self,
        session: Session,
        model: type[M],
        entity_factory: Callable[[M], EntityT],
    ) -> None:
        self._session = session
        self._model = model
        self._entity_factory = entity_factory

    @staticmethod
    def _entity_values(
        entity: EntityT, *, include_none: bool = False
    ) -> dict[str, object]:
        """Build constructor values from dataclass fields inside Infrastructure."""
        return {
            field.name: getattr(entity, field.name)
            for field in fields(entity)  # type: ignore[arg-type]
            if field.name not in {"id", "created_at", "updated_at"}
            and (include_none or getattr(entity, field.name) is not None)
        }

    def _to_entity(self, row: M) -> EntityT:
        """Map a SQLAlchemy row into a domain entity."""
        return self._entity_factory(row)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        """Normalize SQLite's naive timestamp reads to timezone-aware UTC."""
        return (
            value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        )

    def create(self, entity: EntityT) -> EntityT:
        """Persist an entity and return it with its assigned identity."""
        row = self._model(**self._entity_values(entity))
        self._session.add(row)
        self._session.flush()
        return self._to_entity(row)

    def get_by_id(self, entity_id: int) -> EntityT | None:
        """Return a domain entity by primary key."""
        row = self._session.get(self._model, entity_id)
        return None if row is None else self._to_entity(row)

    def list(self, *, limit: int = 100, offset: int = 0) -> list[EntityT]:
        """Return an ordered page of domain entities."""
        if limit < 1 or offset < 0:
            raise ValueError("limit must be positive and offset must not be negative")
        primary_key = self._model.__mapper__.primary_key[0]
        rows = self._session.scalars(
            select(self._model).order_by(primary_key).limit(limit).offset(offset)
        )
        return [self._to_entity(row) for row in rows]

    def update(self, entity: EntityT) -> EntityT | None:
        """Update an existing entity by its identity."""
        entity_id = getattr(entity, "id", None)
        if entity_id is None:
            return None
        row = self._session.get(self._model, entity_id)
        if row is None:
            return None
        for key, value in self._entity_values(entity, include_none=True).items():
            if hasattr(row, key):
                setattr(row, key, value)
        self._session.flush()
        return self._to_entity(row)

    def delete(self, entity_id: int) -> bool:
        """Delete a row; foreign-key rules guard referenced master data."""
        row = self._session.get(self._model, entity_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.flush()
        return True


class IndustrySqlAlchemyRepository(
    SqlAlchemyRepository[IndustryModel, Industry], IndustryRepository
):
    """Industry repository adapter."""

    def __init__(self, session: Session) -> None:
        super().__init__(
            session,
            IndustryModel,
            lambda row: Industry(
                id=row.id,
                code=row.code,
                name=row.name,
                is_active=row.is_active,
                created_at=self._utc(row.created_at),
                updated_at=self._utc(row.updated_at),
            ),
        )


class SubIndustrySqlAlchemyRepository(
    SqlAlchemyRepository[SubIndustryModel, SubIndustry], SubIndustryRepository
):
    """Sub-industry repository adapter."""

    def __init__(self, session: Session) -> None:
        super().__init__(
            session,
            SubIndustryModel,
            lambda row: SubIndustry(
                id=row.id,
                industry_id=row.industry_id,
                code=row.code,
                name=row.name,
                is_active=row.is_active,
                created_at=self._utc(row.created_at),
                updated_at=self._utc(row.updated_at),
            ),
        )


class CompanySqlAlchemyRepository(
    SqlAlchemyRepository[CompanyModel, Company], CompanyRepository
):
    """Company repository adapter."""

    def __init__(self, session: Session) -> None:
        super().__init__(
            session,
            CompanyModel,
            lambda row: Company(
                id=row.id,
                name=row.name,
                country_code=row.country_code,
                fiscal_year_end=row.fiscal_year_end,
                reporting_currency=row.reporting_currency,
                listing_status=row.listing_status,
                created_at=self._utc(row.created_at),
                updated_at=self._utc(row.updated_at),
            ),
        )


class SecuritySqlAlchemyRepository(
    SqlAlchemyRepository[SecurityModel, Security], SecurityRepository
):
    """Security repository adapter."""

    def __init__(self, session: Session) -> None:
        super().__init__(
            session,
            SecurityModel,
            lambda row: Security(
                id=row.id,
                company_id=row.company_id,
                ticker=row.ticker,
                exchange=row.exchange,
                currency=row.currency,
                security_type=row.security_type,
                listing_date=row.listing_date,
                delisting_date=row.delisting_date,
                is_active=row.is_active,
                created_at=self._utc(row.created_at),
                updated_at=self._utc(row.updated_at),
            ),
        )


class DataSourceSqlAlchemyRepository(
    SqlAlchemyRepository[DataSourceModel, DataSource], DataSourceRepository
):
    """Data-source repository adapter."""

    def __init__(self, session: Session) -> None:
        super().__init__(
            session,
            DataSourceModel,
            lambda row: DataSource(
                id=row.id,
                code=row.code,
                name=row.name,
                provider_type=row.provider_type,
                website=row.website,
                licensing_type=row.licensing_type,
                is_active=row.is_active,
                created_at=self._utc(row.created_at),
                updated_at=self._utc(row.updated_at),
            ),
        )
