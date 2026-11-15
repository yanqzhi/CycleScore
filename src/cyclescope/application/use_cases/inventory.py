"""PIT assembly of compatible annual financial data for inventory analysis."""

from decimal import Decimal, localcontext

from cyclescope.application.dto.inventory import (
    CalculateInventoryRequest,
    CalculateInventoryResponse,
)
from cyclescope.application.use_cases.financial_data import (
    FinancialStatementResult,
    GetFinancialStatements,
)
from cyclescope.domain.entities.financial_data import FinancialItem
from cyclescope.domain.entities.inventory import (
    InventoryAnnualObservation,
    InventoryInputReference,
    InventoryStatus,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    FinancialItemRepository,
    InventorySnapshotRepository,
    SecurityRepository,
)
from cyclescope.domain.services.inventory import calculate_inventory
from cyclescope.domain.value_objects.financial_data import StatementType, UnitDimension


class CalculateInventory:
    """Calculate and append annual inventory snapshots at one PIT cutoff."""

    def __init__(
        self,
        financial_query: GetFinancialStatements,
        financial_items: FinancialItemRepository,
        repository: InventorySnapshotRepository,
        securities: SecurityRepository | None = None,
    ) -> None:
        self._financial_query = financial_query
        self._financial_items = financial_items
        self._repository = repository
        self._securities = securities

    def execute(self, request: CalculateInventoryRequest) -> CalculateInventoryResponse:
        if request.security_id is not None and self._securities is not None:
            security = self._securities.get_by_id(request.security_id)
            if security is None or security.company_id != request.company_id:
                raise DomainValidationError("Security does not belong to the company.")
        statements = self._financial_query.execute(
            request.company_id,
            request.as_of,
            source_id=request.financial_source_id,
        )
        statements = [
            row
            for row in statements
            if row.statement.period_end <= request.as_of.date()
            and row.statement.fiscal_period.value == "FY"
            and row.statement.statement_type in {StatementType.BS, StatementType.PL}
        ]
        sources = {row.statement.source_id for row in statements}
        if request.financial_source_id is None and len(sources) > 1:
            raise DomainValidationError(
                "financial_source_id is required when multiple sources are eligible."
            )
        if (
            request.financial_source_id is not None
            and statements
            and sources != {request.financial_source_id}
        ):
            raise DomainValidationError(
                "Financial statements do not match selected source."
            )
        variants = {
            (
                row.statement.source_id,
                row.statement.accounting_standard,
                row.statement.consolidation_scope.value,
                row.statement.reporting_currency,
            )
            for row in statements
        }
        if len(variants) > 1:
            raise DomainValidationError(
                "Financial statements have incompatible source, standard, scope, "
                "or currency."
            )

        inventory_item = self._financial_items.get_by_code("INVENTORIES")
        cogs_item = self._financial_items.get_by_code("COST_OF_GOODS_SOLD")
        self._validate_master(inventory_item, "INVENTORIES", StatementType.BS)
        self._validate_master(cogs_item, "COST_OF_GOODS_SOLD", StatementType.PL)
        by_year: dict[tuple[StatementType, int], FinancialStatementResult] = {}
        for result in statements:
            statement = result.statement
            key = (statement.statement_type, statement.fiscal_year)
            if key in by_year:
                raise DomainValidationError(
                    "Multiple FY statements exist for a fiscal year; source selection "
                    "cannot resolve distinct reporting periods."
                )
            by_year[key] = result

        annual: list[InventoryAnnualObservation] = []
        for year in sorted({year for _, year in by_year}):
            bs = by_year.get((StatementType.BS, year))
            pl = by_year.get((StatementType.PL, year))
            base = bs or pl
            if base is None:
                continue
            base_statement = base.statement
            inv_value, inv_ref = self._line(bs, inventory_item, "INVENTORIES")
            cogs_value, cogs_ref = self._line(pl, cogs_item, "COST_OF_GOODS_SOLD")
            cogs_reason = None
            period_start = pl.statement.period_start if pl is not None else None
            if bs is not None and pl is not None:
                bs_statement = bs.statement
                pl_statement = pl.statement
                if bs_statement.period_end != pl_statement.period_end:
                    cogs_value = None
                    cogs_ref = None
                    cogs_reason = (
                        "Incompatible financial periods: FY period ends differ."
                    )
                elif (
                    bs_statement.reporting_currency != pl_statement.reporting_currency
                    or bs_statement.accounting_standard
                    != pl_statement.accounting_standard
                    or bs_statement.consolidation_scope
                    != pl_statement.consolidation_scope
                    or bs_statement.source_id != pl_statement.source_id
                ):
                    raise DomainValidationError(
                        "Inventory and COGS statements have incompatible source "
                        "metadata."
                    )
            annual.append(
                InventoryAnnualObservation(
                    fiscal_year=year,
                    period_start=period_start,
                    period_end=base_statement.period_end,
                    currency=base_statement.reporting_currency,
                    source_id=base_statement.source_id,
                    accounting_standard=base_statement.accounting_standard,
                    consolidation_scope=base_statement.consolidation_scope.value,
                    closing_inventory=inv_value,
                    cogs=cogs_value,
                    inventory_reference=inv_ref,
                    cogs_reference=cogs_ref,
                    cogs_unavailable_reason=cogs_reason,
                )
            )
        snapshots = calculate_inventory(
            company_id=request.company_id,
            security_id=request.security_id,
            as_of=request.as_of,
            observations=tuple(annual),
            config=request.config,
        )
        persisted = tuple(self._repository.create(row) for row in snapshots)
        if not persisted:
            return CalculateInventoryResponse(
                snapshots=(),
                status=InventoryStatus.UNAVAILABLE,
                unavailable_reason="No PIT-visible annual FY financial statements.",
            )
        return CalculateInventoryResponse(
            snapshots=persisted, status=persisted[-1].status
        )

    @staticmethod
    def _validate_master(
        item: FinancialItem | None, code: str, statement_type: StatementType
    ) -> None:
        if item is not None and (
            item.statement_type != statement_type
            or item.unit_dimension != UnitDimension.CURRENCY_AMOUNT
        ):
            raise DomainValidationError(
                f"Financial master {code} has incompatible units/type."
            )

    @staticmethod
    def _line(
        result: FinancialStatementResult | None,
        item: FinancialItem | None,
        code: str,
    ) -> tuple[Decimal | None, InventoryInputReference | None]:
        if result is None or item is None or item.id is None:
            return None, None
        matches = [line for line in result.items if line.financial_item_id == item.id]
        if len(matches) > 1:
            raise DomainValidationError(f"FY statement has duplicate {code} lines.")
        if not matches:
            return None, None
        line = matches[0]
        statement = result.statement
        if (
            line.currency_code != statement.reporting_currency
            or line.unit_code != "CURRENCY"
        ):
            raise DomainValidationError(f"{code} currency or unit is incompatible.")
        with localcontext() as context:
            context.prec = 80
            value = line.value * line.scale_multiplier
        reference = InventoryInputReference(
            statement_id=statement.id or 0,
            statement_item_id=line.id or 0,
            source_id=statement.source_id,
            revision_number=statement.revision_number,
            fiscal_year=statement.fiscal_year,
            fiscal_period=statement.fiscal_period.value,
            item_code=code,
            period_start=statement.period_start,
            period_end=statement.period_end,
            available_at=statement.available_at,
            publication_date=statement.publication_date,
            publication_datetime=statement.publication_datetime,
        )
        return value, reference
