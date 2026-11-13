"""SQLAlchemy adapters for financial domain repositories."""

from datetime import UTC, date, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from cyclescope.domain.entities.financial_data import (
    FinancialItem,
    FinancialItemMapping,
    FinancialStatement,
    FinancialStatementItem,
)
from cyclescope.domain.repositories.contracts import (
    FinancialItemMappingRepository,
    FinancialItemRepository,
    FinancialStatementItemRepository,
    FinancialStatementRepository,
)
from cyclescope.domain.value_objects.financial_data import (
    ConsolidationScope,
    FiscalPeriod,
    StatementType,
    UnitDimension,
)
from cyclescope.infrastructure.database.models.financial_data import (
    FinancialItemMappingModel,
    FinancialItemModel,
    FinancialStatementItemModel,
    FinancialStatementModel,
)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _required_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _statement(row: FinancialStatementModel) -> FinancialStatement:
    return FinancialStatement(
        id=row.id,
        company_id=row.company_id,
        source_id=row.source_id,
        statement_type=StatementType(row.statement_type),
        accounting_standard=row.accounting_standard,
        consolidation_scope=ConsolidationScope(row.consolidation_scope),
        fiscal_year=row.fiscal_year,
        fiscal_period=FiscalPeriod(row.fiscal_period),
        period_start=row.period_start,
        period_end=row.period_end,
        publication_date=row.publication_date,
        publication_datetime=_utc(row.publication_datetime),
        available_at=_required_utc(row.available_at),
        collected_at=_required_utc(row.collected_at),
        revision_number=row.revision_number,
        reporting_currency=row.reporting_currency,
        source_document_reference=row.source_document_reference,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


def _item(row: FinancialItemModel) -> FinancialItem:
    return FinancialItem(
        id=row.id,
        item_code=row.item_code,
        item_name=row.item_name,
        statement_type=StatementType(row.statement_type),
        category=row.category,
        unit_dimension=UnitDimension(row.unit_dimension),
        description=row.description,
        is_active=row.is_active,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


class SQLAlchemyFinancialStatementRepository(FinancialStatementRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, entity: FinancialStatement) -> FinancialStatement:
        row = FinancialStatementModel(
            company_id=entity.company_id,
            source_id=entity.source_id,
            statement_type=entity.statement_type.value,
            accounting_standard=entity.accounting_standard,
            consolidation_scope=entity.consolidation_scope.value,
            fiscal_year=entity.fiscal_year,
            fiscal_period=entity.fiscal_period.value,
            period_start=entity.period_start,
            period_end=entity.period_end,
            publication_date=entity.publication_date,
            publication_datetime=entity.publication_datetime,
            available_at=entity.available_at,
            collected_at=entity.collected_at,
            revision_number=entity.revision_number,
            reporting_currency=entity.reporting_currency,
            source_document_reference=entity.source_document_reference,
        )
        self.session.add(row)
        self.session.flush()
        return _statement(row)

    def get_by_id(self, entity_id: int) -> FinancialStatement | None:
        row = self.session.get(FinancialStatementModel, entity_id)
        return _statement(row) if row else None

    def list_by_company(self, company_id: int) -> list[FinancialStatement]:
        return [
            _statement(x)
            for x in self.session.scalars(
                select(FinancialStatementModel)
                .where(FinancialStatementModel.company_id == company_id)
                .order_by(
                    FinancialStatementModel.period_end.desc(),
                    FinancialStatementModel.source_id,
                )
            )
        ]

    def get_available_as_of(
        self,
        company_id: int,
        as_of: datetime,
        *,
        statement_type: StatementType | None = None,
        source_id: int | None = None,
    ) -> list[FinancialStatement]:
        q = select(FinancialStatementModel).where(
            FinancialStatementModel.company_id == company_id,
            FinancialStatementModel.available_at <= as_of,
        )
        if statement_type is not None:
            q = q.where(FinancialStatementModel.statement_type == statement_type.value)
        if source_id is not None:
            q = q.where(FinancialStatementModel.source_id == source_id)
        return [
            _statement(x)
            for x in self.session.scalars(
                q.order_by(
                    FinancialStatementModel.period_end,
                    FinancialStatementModel.source_id,
                    FinancialStatementModel.revision_number,
                )
            )
        ]

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
    ) -> list[FinancialStatement]:
        q = (
            select(FinancialStatementModel)
            .where(
                FinancialStatementModel.company_id == company_id,
                FinancialStatementModel.source_id == source_id,
                FinancialStatementModel.statement_type == statement_type.value,
                FinancialStatementModel.period_start == period_start,
                FinancialStatementModel.period_end == period_end,
                FinancialStatementModel.accounting_standard == accounting_standard,
                FinancialStatementModel.consolidation_scope
                == consolidation_scope.value,
                FinancialStatementModel.fiscal_year == fiscal_year,
                FinancialStatementModel.fiscal_period == fiscal_period.value,
            )
            .order_by(FinancialStatementModel.revision_number)
        )
        return [_statement(x) for x in self.session.scalars(q)]

    def exists_revision(self, e: FinancialStatement) -> bool:
        return any(
            x.revision_number == e.revision_number
            for x in self.get_revisions(
                e.company_id,
                e.source_id,
                e.statement_type,
                e.period_start,
                e.period_end,
                e.accounting_standard,
                e.consolidation_scope,
                e.fiscal_year,
                e.fiscal_period,
            )
        )


class SQLAlchemyFinancialItemRepository(FinancialItemRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, e: FinancialItem) -> FinancialItem:
        r = FinancialItemModel(
            item_code=e.item_code,
            item_name=e.item_name,
            statement_type=e.statement_type.value,
            category=e.category,
            unit_dimension=e.unit_dimension.value,
            description=e.description,
            is_active=e.is_active,
        )
        self.session.add(r)
        self.session.flush()
        return _item(r)

    def get_by_id(self, i: int) -> FinancialItem | None:
        r = self.session.get(FinancialItemModel, i)
        return _item(r) if r else None

    def get_by_code(self, c: str) -> FinancialItem | None:
        r = self.session.scalar(
            select(FinancialItemModel).where(FinancialItemModel.item_code == c)
        )
        return _item(r) if r else None

    def list_by_statement_type(self, t: StatementType) -> list[FinancialItem]:
        return [
            _item(r)
            for r in self.session.scalars(
                select(FinancialItemModel).where(
                    FinancialItemModel.statement_type == t.value
                )
            )
        ]


class SQLAlchemyFinancialStatementItemRepository(FinancialStatementItemRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, e: FinancialStatementItem) -> FinancialStatementItem:
        r = FinancialStatementItemModel(
            financial_statement_id=e.financial_statement_id,
            financial_item_id=e.financial_item_id,
            value=e.value,
            currency_code=e.currency_code,
            unit_code=e.unit_code,
            scale_multiplier=e.scale_multiplier,
        )
        self.session.add(r)
        self.session.flush()
        return FinancialStatementItem(
            id=r.id,
            financial_statement_id=r.financial_statement_id,
            financial_item_id=r.financial_item_id,
            value=r.value,
            currency_code=r.currency_code,
            unit_code=r.unit_code,
            scale_multiplier=r.scale_multiplier,
            created_at=_utc(r.created_at),
            updated_at=_utc(r.updated_at),
        )

    def list_by_statement(self, i: int) -> list[FinancialStatementItem]:
        return [
            FinancialStatementItem(
                id=r.id,
                financial_statement_id=r.financial_statement_id,
                financial_item_id=r.financial_item_id,
                value=r.value,
                currency_code=r.currency_code,
                unit_code=r.unit_code,
                scale_multiplier=r.scale_multiplier,
                created_at=_utc(r.created_at),
                updated_at=_utc(r.updated_at),
            )
            for r in self.session.scalars(
                select(FinancialStatementItemModel).where(
                    FinancialStatementItemModel.financial_statement_id == i
                )
            )
        ]


class SQLAlchemyFinancialItemMappingRepository(FinancialItemMappingRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, e: FinancialItemMapping) -> FinancialItemMapping:
        r = FinancialItemMappingModel(
            source_id=e.source_id,
            source_item_code=e.source_item_code,
            source_item_name=e.source_item_name,
            financial_item_id=e.financial_item_id,
            accounting_standard=e.accounting_standard,
        )
        self.session.add(r)
        self.session.flush()
        return FinancialItemMapping(
            id=r.id,
            source_id=r.source_id,
            source_item_code=r.source_item_code,
            source_item_name=r.source_item_name,
            financial_item_id=r.financial_item_id,
            accounting_standard=r.accounting_standard,
            created_at=_utc(r.created_at),
            updated_at=_utc(r.updated_at),
        )

    def exists_mapping(
        self, source_id: int, source_item_code: str, accounting_standard: str | None
    ) -> bool:
        q = select(FinancialItemMappingModel.id).where(
            FinancialItemMappingModel.source_id == source_id,
            FinancialItemMappingModel.source_item_code == source_item_code,
            FinancialItemMappingModel.accounting_standard == accounting_standard,
        )
        return self.session.scalar(q) is not None

    def resolve_source_item(
        self,
        source_id: int,
        source_item_code: str,
        accounting_standard: str | None = None,
    ) -> FinancialItemMapping | None:
        q = select(FinancialItemMappingModel).where(
            FinancialItemMappingModel.source_id == source_id,
            FinancialItemMappingModel.source_item_code == source_item_code,
        )
        if accounting_standard is None:
            q = q.where(FinancialItemMappingModel.accounting_standard.is_(None))
        else:
            q = q.where(
                or_(
                    FinancialItemMappingModel.accounting_standard
                    == accounting_standard,
                    FinancialItemMappingModel.accounting_standard.is_(None),
                )
            )
        rows = list(self.session.scalars(q))
        if not rows:
            return None
        rows.sort(key=lambda r: r.accounting_standard is None)
        r = rows[0]
        return FinancialItemMapping(
            id=r.id,
            source_id=r.source_id,
            source_item_code=r.source_item_code,
            source_item_name=r.source_item_name,
            financial_item_id=r.financial_item_id,
            accounting_standard=r.accounting_standard,
            created_at=_utc(r.created_at),
            updated_at=_utc(r.updated_at),
        )
