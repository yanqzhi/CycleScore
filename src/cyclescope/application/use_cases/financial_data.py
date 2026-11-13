"""Provider-neutral financial statement application commands and queries."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from cyclescope.domain.entities.financial_data import (
    FinancialItem,
    FinancialItemMapping,
    FinancialStatement,
    FinancialStatementItem,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    CompanyRepository,
    DataSourceRepository,
    FinancialItemMappingRepository,
    FinancialItemRepository,
    FinancialStatementItemRepository,
    FinancialStatementRepository,
)
from cyclescope.domain.value_objects.financial_data import (
    ConsolidationScope,
    FiscalPeriod,
    StatementType,
)


@dataclass(frozen=True, slots=True)
class FinancialLineInput:
    item_id: int
    value: Decimal
    unit_code: str
    scale_multiplier: int = 1
    currency_code: str | None = None


@dataclass(frozen=True, slots=True)
class ImportFinancialStatementInput:
    company_id: int
    source_id: int
    statement_type: StatementType
    accounting_standard: str
    consolidation_scope: ConsolidationScope
    fiscal_year: int
    fiscal_period: FiscalPeriod
    period_start: date | None
    period_end: date
    publication_date: date
    publication_datetime: datetime | None
    available_at: datetime
    collected_at: datetime
    revision_number: int
    reporting_currency: str
    items: tuple[FinancialLineInput, ...]
    source_document_reference: str | None = None


@dataclass(frozen=True, slots=True)
class FinancialStatementResult:
    statement: FinancialStatement
    items: tuple[FinancialStatementItem, ...]


class RegisterFinancialItem:
    def __init__(self, repository: FinancialItemRepository) -> None:
        self.repository = repository

    def execute(self, item: FinancialItem) -> FinancialItem:
        if self.repository.get_by_code(item.item_code) is not None:
            raise DomainValidationError("Financial item code already exists.")
        return self.repository.create(item)


class RegisterFinancialItemMapping:
    def __init__(
        self,
        repository: FinancialItemMappingRepository,
        items: FinancialItemRepository,
        sources: DataSourceRepository,
    ) -> None:
        self.repository, self.items, self.sources = repository, items, sources

    def execute(self, mapping: FinancialItemMapping) -> FinancialItemMapping:
        if self.sources.get_by_id(mapping.source_id) is None:
            raise DomainValidationError("Unknown data source.")
        target_item = self.items.get_by_id(mapping.financial_item_id)
        if target_item is None:
            raise DomainValidationError("Unknown financial item.")
        if not target_item.is_active:
            raise DomainValidationError("Cannot map an inactive financial item.")
        if self.repository.exists_mapping(
            mapping.source_id, mapping.source_item_code, mapping.accounting_standard
        ):
            raise DomainValidationError(
                "Source item mapping already exists in this scope."
            )
        return self.repository.create(mapping)


class ImportFinancialStatement:
    def __init__(
        self,
        statements: FinancialStatementRepository,
        statement_items: FinancialStatementItemRepository,
        items: FinancialItemRepository,
        companies: CompanyRepository,
        sources: DataSourceRepository,
    ) -> None:
        (
            self.statements,
            self.statement_items,
            self.items,
            self.companies,
            self.sources,
        ) = statements, statement_items, items, companies, sources

    def execute(
        self, request: ImportFinancialStatementInput
    ) -> FinancialStatementResult:
        if self.companies.get_by_id(request.company_id) is None:
            raise DomainValidationError("Unknown company.")
        if self.sources.get_by_id(request.source_id) is None:
            raise DomainValidationError("Unknown data source.")
        if not request.items:
            raise DomainValidationError("A statement must contain at least one item.")
        ids = [line.item_id for line in request.items]
        if len(ids) != len(set(ids)):
            raise DomainValidationError("Duplicate financial item within statement.")
        statement = FinancialStatement(
            company_id=request.company_id,
            source_id=request.source_id,
            statement_type=request.statement_type,
            accounting_standard=request.accounting_standard,
            consolidation_scope=request.consolidation_scope,
            fiscal_year=request.fiscal_year,
            fiscal_period=request.fiscal_period,
            period_start=request.period_start,
            period_end=request.period_end,
            publication_date=request.publication_date,
            publication_datetime=request.publication_datetime,
            available_at=request.available_at,
            collected_at=request.collected_at,
            revision_number=request.revision_number,
            reporting_currency=request.reporting_currency,
            source_document_reference=request.source_document_reference,
        )
        if self.statements.exists_revision(statement):
            raise DomainValidationError("Statement revision already exists.")
        resolved = []
        for line in request.items:
            item = self.items.get_by_id(line.item_id)
            if item is None:
                raise DomainValidationError(f"Unknown financial item {line.item_id}.")
            if not item.is_active:
                raise DomainValidationError(
                    f"Financial item {line.item_id} is inactive for new imports."
                )
            value = FinancialStatementItem(
                financial_statement_id=0,
                financial_item_id=line.item_id,
                value=line.value,
                currency_code=line.currency_code,
                unit_code=line.unit_code,
                scale_multiplier=line.scale_multiplier,
            )
            value.validate_for(item, statement)
            resolved.append(value)
        stored_statement = self.statements.create(statement)
        stored_items = tuple(
            self.statement_items.create(
                FinancialStatementItem(
                    financial_statement_id=stored_statement.id or 0,
                    financial_item_id=x.financial_item_id,
                    value=x.value,
                    currency_code=x.currency_code,
                    unit_code=x.unit_code,
                    scale_multiplier=x.scale_multiplier,
                )
            )
            for x in resolved
        )
        return FinancialStatementResult(stored_statement, stored_items)


class GetFinancialStatements:
    """Read visible statements using a UTC-normalized availability cutoff.

    SQLite may return stored timestamps without timezone metadata, so the
    repository comparison contract is that every query cutoff is UTC-aware.
    """

    def __init__(
        self,
        statements: FinancialStatementRepository,
        statement_items: FinancialStatementItemRepository,
    ) -> None:
        self.statements, self.statement_items = statements, statement_items

    def execute(
        self,
        company_id: int,
        as_of: datetime,
        *,
        statement_type: StatementType | None = None,
        source_id: int | None = None,
    ) -> list[FinancialStatementResult]:
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        as_of_utc = as_of.astimezone(UTC)
        visible = self.statements.get_available_as_of(
            company_id,
            as_of_utc,
            statement_type=statement_type,
            source_id=source_id,
        )
        latest: dict[
            tuple[int, str, str, str, int, str, date | None, date], FinancialStatement
        ] = {}
        for row in visible:
            key = (
                row.source_id,
                row.statement_type.value,
                row.accounting_standard,
                row.consolidation_scope.value,
                row.fiscal_year,
                row.fiscal_period.value,
                row.period_start,
                row.period_end,
            )
            old = latest.get(key)
            if old is None or (row.revision_number, row.available_at) > (
                old.revision_number,
                old.available_at,
            ):
                latest[key] = row
        return [
            FinancialStatementResult(
                row, tuple(self.statement_items.list_by_statement(row.id or 0))
            )
            for row in latest.values()
        ]


class GetFinancialStatementAsOf:
    def __init__(self, query: GetFinancialStatements) -> None:
        self.query = query

    def execute(
        self,
        company_id: int,
        statement_type: StatementType,
        fiscal_year: int,
        fiscal_period: FiscalPeriod,
        as_of: datetime,
        *,
        source_id: int | None = None,
    ) -> FinancialStatementResult | None:
        matches = [
            x
            for x in self.query.execute(
                company_id, as_of, statement_type=statement_type, source_id=source_id
            )
            if x.statement.fiscal_year == fiscal_year
            and x.statement.fiscal_period == fiscal_period
        ]
        if source_id is None and len({x.statement.source_id for x in matches}) > 1:
            raise DomainValidationError(
                "source_id is required when multiple sources match."
            )
        if len(matches) > 1:
            raise DomainValidationError(
                "Reporting-period query is ambiguous; narrow the period filters."
            )
        return matches[0] if matches else None
