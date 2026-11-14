"""Build one-currency, source-scoped valuation inputs from existing PIT services."""

from collections import defaultdict
from decimal import Decimal

from cyclescope.application.dto.market_data_access import (
    PriceObservationAsOfRequest,
    PriceQueryScope,
)
from cyclescope.application.dto.valuation import ValuationInputRequest
from cyclescope.application.use_cases.financial_data import (
    FinancialStatementResult,
    GetFinancialStatements,
)
from cyclescope.application.use_cases.market_data_access import MarketDataAccess
from cyclescope.domain.entities.financial_data import (
    FinancialItem,
    FinancialStatementItem,
)
from cyclescope.domain.entities.valuation import (
    ValuationInputReference,
    ValuationInputs,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    FinancialItemRepository,
    SecurityRepository,
)
from cyclescope.domain.services.financial_periods import (
    IncomePeriodAmount,
    TrailingAmount,
    select_trailing_twelve_months,
)
from cyclescope.domain.value_objects.financial_data import (
    StatementType,
    UnitDimension,
    validate_item_unit,
)

_FLOW_CODES = (
    "NET_INCOME",
    "OPERATING_PROFIT",
    "DEPRECIATION_AMORTIZATION",
    "EPS",
    "WEIGHTED_AVERAGE_SHARES",
)
_BALANCE_CODES = (
    "TOTAL_EQUITY",
    "CASH_AND_CASH_EQUIVALENTS",
    "SHORT_TERM_DEBT",
    "LONG_TERM_DEBT",
    "SHARES_OUTSTANDING",
)


class BuildValuationInputs:
    """Reuse statement and market access services with an explicit shared cutoff."""

    def __init__(
        self,
        securities: SecurityRepository,
        financial_items: FinancialItemRepository,
        financial_query: GetFinancialStatements,
        market_data: MarketDataAccess,
    ) -> None:
        self._securities = securities
        self._financial_items = financial_items
        self._financial_query = financial_query
        self._market_data = market_data

    def execute(self, request: ValuationInputRequest) -> ValuationInputs:
        security = self._securities.get_by_id(request.security_id)
        if security is None:
            raise DomainValidationError("Unknown security.")
        market_result = self._market_data.get_price_observation_as_of(
            PriceObservationAsOfRequest(
                PriceQueryScope(request.security_id, request.market_source_id),
                request.valuation_date,
                request.as_of,
            )
        )
        prices = sorted(market_result.observations, key=lambda row: row.source_id)
        price = prices[0] if prices else None

        statements = self._financial_query.execute(
            security.company_id,
            request.as_of,
            source_id=request.financial_source_id,
        )
        statements = [
            row
            for row in statements
            if row.statement.period_end <= request.valuation_date
        ]
        sources = {row.statement.source_id for row in statements}
        if request.financial_source_id is None and len(sources) > 1:
            raise DomainValidationError(
                "financial_source_id is required when multiple sources are eligible."
            )
        variants = {
            (
                row.statement.accounting_standard,
                row.statement.consolidation_scope,
                row.statement.reporting_currency,
            )
            for row in statements
        }
        if len(variants) > 1:
            raise DomainValidationError(
                "Financial statements with different standards/scopes cannot be mixed."
            )
        financial_source_id = next(iter(sources), None)

        items_by_id: dict[int, FinancialItem] = {}

        def financial_item(item_id: int) -> FinancialItem | None:
            if item_id not in items_by_id:
                item = self._financial_items.get_by_id(item_id)
                if item is not None:
                    items_by_id[item_id] = item
                else:
                    return None
            return items_by_id[item_id]

        references: list[ValuationInputReference] = []
        if price is not None:
            references.append(
                ValuationInputReference(
                    record_type="DAILY_PRICE",
                    record_id=price.id or 0,
                    source_id=price.source_id,
                    revision_number=price.revision_number,
                    available_at=price.available_at,
                    observation_date=price.observation_date,
                )
            )

        balance_values: dict[str, Decimal] = {}
        balance_period = None
        balance_statements = [
            row
            for row in statements
            if row.statement.statement_type == StatementType.BS
        ]
        balance_statement = max(
            balance_statements,
            key=lambda row: (
                row.statement.period_end,
                row.statement.available_at,
                row.statement.revision_number,
            ),
            default=None,
        )
        if balance_statement is not None:
            balance_period = balance_statement.statement.fiscal_period.value
            for line in balance_statement.items:
                item = financial_item(line.financial_item_id)
                if item is None or item.item_code not in _BALANCE_CODES:
                    continue
                self._validate_item_unit(item, line.unit_code, line.currency_code)
                self._validate_line_currency(line.currency_code, balance_statement)
                balance_values[item.item_code] = line.value * line.scale_multiplier
                references.append(
                    self._financial_reference(balance_statement, line, item)
                )

        flow_rows: dict[
            str,
            list[
                tuple[FinancialStatementResult, FinancialStatementItem, FinancialItem]
            ],
        ] = defaultdict(list)
        for statement_result in statements:
            statement = statement_result.statement
            if statement.statement_type != StatementType.PL:
                continue
            for line in statement_result.items:
                item = financial_item(line.financial_item_id)
                if item is None or item.item_code not in _FLOW_CODES:
                    continue
                self._validate_item_unit(item, line.unit_code, line.currency_code)
                self._validate_line_currency(line.currency_code, statement_result)
                flow_rows[item.item_code].append((statement_result, line, item))

        selected: dict[
            str, tuple[TrailingAmount, tuple[FinancialStatementResult, ...]]
        ] = {}
        for code, rows in flow_rows.items():
            if code == "WEIGHTED_AVERAGE_SHARES":
                continue
            period_inputs = tuple(
                IncomePeriodAmount(
                    value=line.value * line.scale_multiplier,
                    fiscal_year=result.statement.fiscal_year,
                    fiscal_period=result.statement.fiscal_period,
                    period_start=result.statement.period_start
                    or result.statement.period_end,
                    period_end=result.statement.period_end,
                    statement_id=result.statement.id or 0,
                )
                for result, line, _item in rows
            )
            amount = select_trailing_twelve_months(
                period_inputs,
                request.valuation_date,
                aggregate_quarters=code != "EPS",
            )
            selected_rows = tuple(
                result
                for result, _line, _item in rows
                if result.statement.id in amount.statement_ids
            )
            selected[code] = amount, selected_rows

        flow_values: dict[str, Decimal] = {}
        flow_labels: list[str] = []
        for code, (amount, _selected_rows) in selected.items():
            if amount.value is None:
                continue
            # Operating profit and D&A must describe the same period. Other
            # metrics (especially directly reported EPS) select independently.
            if code in {"OPERATING_PROFIT", "DEPRECIATION_AMORTIZATION"}:
                counterpart = (
                    "DEPRECIATION_AMORTIZATION"
                    if code == "OPERATING_PROFIT"
                    else "OPERATING_PROFIT"
                )
                other = selected.get(counterpart)
                if other is None or (
                    amount.period_start,
                    amount.period_end,
                ) != (other[0].period_start, other[0].period_end):
                    continue
            flow_values[code] = amount.value
            flow_labels.append(amount.period_label or "")
            selected_ids = set(amount.statement_ids)
            for result, line, item in flow_rows[code]:
                if result.statement.id in selected_ids:
                    references.append(self._financial_reference(result, line, item))

        net_income_selection = selected.get("NET_INCOME")
        if net_income_selection is not None:
            net_income_period, net_income_rows = net_income_selection
            if net_income_period.value is not None:
                share_rows = flow_rows.get("WEIGHTED_AVERAGE_SHARES", [])
                aligned_shares = self._weighted_average_shares(
                    net_income_period, share_rows
                )
                if aligned_shares is not None:
                    flow_values["WEIGHTED_AVERAGE_SHARES"] = aligned_shares
                    for result, line, item in share_rows:
                        if result.statement.id in net_income_period.statement_ids:
                            references.append(
                                self._financial_reference(result, line, item)
                            )

        financial_currency = next(
            (row.statement.reporting_currency for row in statements), None
        )
        if (
            price is not None
            and financial_currency is not None
            and price.currency != financial_currency
        ):
            raise DomainValidationError(
                "Market price currency and financial reporting currency must match."
            )
        currency = price.currency if price is not None else financial_currency
        return ValuationInputs(
            security_id=request.security_id,
            observation_date=request.valuation_date,
            as_of=request.as_of,
            currency=currency,
            closing_price=price.close if price is not None else None,
            adjusted_closing_price=price.adjusted_close if price is not None else None,
            reported_eps=flow_values.get("EPS"),
            net_income=flow_values.get("NET_INCOME"),
            total_equity=balance_values.get("TOTAL_EQUITY"),
            cash_and_equivalents=balance_values.get("CASH_AND_CASH_EQUIVALENTS"),
            short_term_debt=balance_values.get("SHORT_TERM_DEBT"),
            long_term_debt=balance_values.get("LONG_TERM_DEBT"),
            operating_profit=flow_values.get("OPERATING_PROFIT"),
            depreciation_amortization=flow_values.get("DEPRECIATION_AMORTIZATION"),
            shares_outstanding=balance_values.get("SHARES_OUTSTANDING"),
            weighted_average_shares=flow_values.get("WEIGHTED_AVERAGE_SHARES"),
            price_source_id=price.source_id if price is not None else None,
            price_revision_number=price.revision_number if price is not None else None,
            price_observation_id=price.id if price is not None else None,
            price_available_at=price.available_at if price is not None else None,
            financial_statement_ids=tuple(
                sorted(
                    {ref.parent_record_id for ref in references if ref.parent_record_id}
                )
            ),
            financial_source_ids=(financial_source_id,)
            if financial_source_id is not None
            else (),
            financial_statement_available_ats=tuple(
                sorted(
                    {
                        ref.available_at
                        for ref in references
                        if ref.record_type == "FINANCIAL_LINE"
                    }
                )
            ),
            financial_period=(
                f"FLOW:{','.join(sorted(set(flow_labels)))};"
                f"BALANCE:{balance_period or 'UNAVAILABLE'}"
            ),
            input_references=tuple(references),
        )

    @staticmethod
    def _validate_line_currency(
        currency_code: str | None, statement: FinancialStatementResult
    ) -> None:
        if (
            currency_code is not None
            and currency_code != statement.statement.reporting_currency
        ):
            raise DomainValidationError(
                "Financial item currency differs from its statement reporting currency."
            )

    @staticmethod
    def _validate_item_unit(
        item: FinancialItem, unit_code: str, currency_code: str | None
    ) -> None:
        dimensions = {
            "EPS": UnitDimension.PER_SHARE,
            "WEIGHTED_AVERAGE_SHARES": UnitDimension.SHARES,
            "SHARES_OUTSTANDING": UnitDimension.SHARES,
        }
        expected = dimensions.get(item.item_code, UnitDimension.CURRENCY_AMOUNT)
        if item.unit_dimension != expected:
            raise DomainValidationError(
                f"Financial item {item.item_code} has an incompatible unit dimension."
            )
        validate_item_unit(item.unit_dimension, unit_code, currency_code)

    @staticmethod
    def _financial_reference(
        result: FinancialStatementResult,
        line: FinancialStatementItem,
        item: FinancialItem,
    ) -> ValuationInputReference:
        statement = result.statement
        return ValuationInputReference(
            record_type="FINANCIAL_LINE",
            record_id=line.id or 0,
            parent_record_id=statement.id,
            source_id=statement.source_id,
            revision_number=statement.revision_number,
            available_at=statement.available_at,
            financial_item_code=item.item_code,
            financial_period=statement.fiscal_period.value,
            period_start=statement.period_start,
            period_end=statement.period_end,
            publication_date=statement.publication_date,
            publication_datetime=statement.publication_datetime,
        )

    @staticmethod
    def _weighted_average_shares(
        income_period: TrailingAmount,
        share_rows: list[
            tuple[FinancialStatementResult, FinancialStatementItem, FinancialItem]
        ],
    ) -> Decimal | None:
        selected = [
            (result, line)
            for result, line, _item in share_rows
            if result.statement.id in income_period.statement_ids
        ]
        if not selected:
            selected = [
                (result, line)
                for result, line, _item in share_rows
                if result.statement.period_start == income_period.period_start
                and result.statement.period_end == income_period.period_end
            ]
        if len(selected) == 1:
            result, line = selected[0]
            return line.value * line.scale_multiplier
        if len(selected) != 4:
            return None
        days = [
            (result.statement.period_end - result.statement.period_start).days + 1
            for result, _line in selected
            if result.statement.period_start is not None
        ]
        if len(days) != 4 or sum(days) < 330 or sum(days) > 400:
            return None
        return sum(
            (
                line.value * line.scale_multiplier * day_count
                for (result, line), day_count in zip(selected, days, strict=True)
            ),
            Decimal(0),
        ) / sum(days)
