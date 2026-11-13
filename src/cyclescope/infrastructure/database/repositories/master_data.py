"""SQLAlchemy adapters that translate rows to domain entities."""

from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import DeclarativeBase, Session

from cyclescope.domain.entities import (
    Company,
    CompanyIndustryExposure,
    DataSource,
    Exchange,
    Industry,
    Listing,
    ListingStatusEvent,
    Security,
    SecurityIdentifier,
    SubIndustry,
)
from cyclescope.domain.repositories.contracts import (
    CompanyIndustryExposureRepository,
    CompanyRepository,
    DataSourceRepository,
    ExchangeRepository,
    IndustryRepository,
    ListingRepository,
    ListingStatusEventRepository,
    SecurityIdentifierRepository,
    SecurityRepository,
    SubIndustryRepository,
)
from cyclescope.domain.value_objects.security_identifier import (
    IdentifierScopeKind,
    IdentifierUniquenessScope,
)
from cyclescope.infrastructure.database.models import (
    CompanyIndustryExposureModel,
    CompanyModel,
    DataSourceModel,
    ExchangeModel,
    IndustryModel,
    ListingModel,
    ListingStatusEventModel,
    SecurityIdentifierModel,
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

    def _entity_values(
        self, entity: EntityT, *, include_none: bool = False
    ) -> dict[str, object]:
        """Build constructor values from dataclass fields inside Infrastructure."""
        return {
            field.name: getattr(entity, field.name)
            for field in fields(entity)  # type: ignore[arg-type]
            if field.name not in {"id", "created_at", "updated_at"}
            and hasattr(self._model, field.name)
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
                security_type=row.security_type,
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


class ExchangeSqlAlchemyRepository(
    SqlAlchemyRepository[ExchangeModel, Exchange], ExchangeRepository
):
    """Exchange repository adapter."""

    def __init__(self, session: Session) -> None:
        super().__init__(
            session,
            ExchangeModel,
            lambda row: Exchange(
                exchange_id=row.id,
                exchange_code=row.exchange_code,
                exchange_name=row.exchange_name,
                country_code=row.country_code,
                market_region=row.market_region,
                timezone=row.timezone,
                currency_code=row.currency_code,
                is_active=row.is_active,
                created_at=self._utc(row.created_at),
                updated_at=self._utc(row.updated_at),
            ),
        )


class SecurityIdentifierSqlAlchemyRepository(
    SqlAlchemyRepository[SecurityIdentifierModel, SecurityIdentifier],
    SecurityIdentifierRepository,
):
    """Security identifier repository adapter."""

    def __init__(self, session: Session) -> None:
        super().__init__(
            session,
            SecurityIdentifierModel,
            lambda row: SecurityIdentifier(
                id=row.id,
                security_id=row.security_id,
                identifier_type=row.identifier_type,
                identifier_value=row.identifier_value,
                exchange_id=row.exchange_id,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                created_at=self._utc(row.created_at),
                updated_at=self._utc(row.updated_at),
            ),
        )

    def list_by_security(self, security_id: int) -> list[SecurityIdentifier]:
        rows = self._session.scalars(
            select(SecurityIdentifierModel)
            .where(SecurityIdentifierModel.security_id == security_id)
            .order_by(SecurityIdentifierModel.valid_from, SecurityIdentifierModel.id)
        )
        return [self._to_entity(row) for row in rows]

    def list_by_identifier(
        self,
        identifier_type: str,
        identifier_value: str,
        scope: IdentifierUniquenessScope,
    ) -> list[SecurityIdentifier]:
        statement = select(SecurityIdentifierModel).where(
            SecurityIdentifierModel.identifier_type == identifier_type,
            SecurityIdentifierModel.identifier_value == identifier_value,
        )
        if scope.kind is IdentifierScopeKind.EXCHANGE:
            statement = statement.where(
                SecurityIdentifierModel.exchange_id == scope.exchange_id
            )
        rows = self._session.scalars(statement)
        return [self._to_entity(row) for row in rows]


class ListingSqlAlchemyRepository(
    SqlAlchemyRepository[ListingModel, Listing], ListingRepository
):
    """Listing history repository adapter."""

    def __init__(self, session: Session) -> None:
        super().__init__(
            session,
            ListingModel,
            lambda row: Listing(
                id=row.id,
                security_id=row.security_id,
                exchange_id=row.exchange_id,
                ticker=row.ticker,
                trading_currency=row.trading_currency,
                listing_date=row.listing_date,
                delisting_date=row.delisting_date,
                status=row.status,
                created_at=self._utc(row.created_at),
                updated_at=self._utc(row.updated_at),
            ),
        )

    def list_by_security(self, security_id: int) -> list[Listing]:
        rows = self._session.scalars(
            select(ListingModel)
            .where(ListingModel.security_id == security_id)
            .order_by(ListingModel.listing_date, ListingModel.id)
        )
        return [self._to_entity(row) for row in rows]

    def list_by_exchange_ticker(self, exchange_id: int, ticker: str) -> list[Listing]:
        rows = self._session.scalars(
            select(ListingModel).where(
                ListingModel.exchange_id == exchange_id,
                ListingModel.ticker == ticker,
            )
        )
        return [self._to_entity(row) for row in rows]


class CompanyIndustryExposureSqlAlchemyRepository(
    SqlAlchemyRepository[CompanyIndustryExposureModel, CompanyIndustryExposure],
    CompanyIndustryExposureRepository,
):
    """Company industry exposure repository adapter."""

    def __init__(self, session: Session) -> None:
        super().__init__(
            session,
            CompanyIndustryExposureModel,
            lambda row: CompanyIndustryExposure(
                id=row.id,
                company_id=row.company_id,
                sub_industry_id=row.sub_industry_id,
                revenue_share=row.revenue_share,
                valid_from=row.valid_from,
                valid_to=row.valid_to,
                source_id=row.source_id,
                created_at=self._utc(row.created_at),
                updated_at=self._utc(row.updated_at),
            ),
        )

    def list_by_company(self, company_id: int) -> list[CompanyIndustryExposure]:
        rows = self._session.scalars(
            select(CompanyIndustryExposureModel)
            .where(CompanyIndustryExposureModel.company_id == company_id)
            .order_by(
                CompanyIndustryExposureModel.valid_from, CompanyIndustryExposureModel.id
            )
        )
        return [self._to_entity(row) for row in rows]


class ListingStatusEventSqlAlchemyRepository(ListingStatusEventRepository):
    """Append-only listing status event adapter."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, event: ListingStatusEvent) -> ListingStatusEvent:
        row = ListingStatusEventModel(
            listing_id=event.listing_id,
            status=event.status,
            effective_date=event.effective_date,
        )
        self._session.add(row)
        self._session.flush()
        created_at = row.created_at
        return ListingStatusEvent(
            id=row.id,
            listing_id=row.listing_id,
            status=row.status,
            effective_date=row.effective_date,
            created_at=(
                created_at.replace(tzinfo=UTC)
                if created_at.tzinfo is None
                else created_at.astimezone(UTC)
            ),
        )

    def list_by_listing(self, listing_id: int) -> list[ListingStatusEvent]:
        rows = self._session.scalars(
            select(ListingStatusEventModel)
            .where(ListingStatusEventModel.listing_id == listing_id)
            .order_by(ListingStatusEventModel.effective_date)
        )
        return [
            ListingStatusEvent(
                id=row.id,
                listing_id=row.listing_id,
                status=row.status,
                effective_date=row.effective_date,
                created_at=(
                    row.created_at.replace(tzinfo=UTC)
                    if row.created_at.tzinfo is None
                    else row.created_at.astimezone(UTC)
                ),
            )
            for row in rows
        ]
