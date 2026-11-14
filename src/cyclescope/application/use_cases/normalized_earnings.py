"""PIT assembly, analysis, valuation, and append-only save for normalized earnings."""

from dataclasses import replace
from datetime import UTC
from decimal import Decimal

from cyclescope.application.dto.normalized_earnings import NormalizedEarningsRequest
from cyclescope.application.use_cases.financial_data import GetFinancialStatements
from cyclescope.domain.entities.normalized_earnings import (
    EarningsInputReference,
    EarningsMetric,
    EarningsResultStatus,
    FiscalEarningsObservation,
    NormalizedEarningsResult,
    analyze_historical_earnings,
)
from cyclescope.domain.entities.valuation import (
    ValuationInputReference,
    ValuationMetricCode,
    ValuationResultStatus,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    FinancialItemRepository,
    NormalizedEarningsRepository,
)
from cyclescope.domain.services.valuation import (
    calculate_metric,
    default_metric_definitions,
)
from cyclescope.domain.value_objects.financial_data import StatementType

_CODE_BY_METRIC = {
    EarningsMetric.OPERATING_PROFIT: "OPERATING_PROFIT",
    EarningsMetric.NET_INCOME: "NET_INCOME",
    EarningsMetric.EPS: "EPS",
}


class CalculateNormalizedEarnings:
    """Calculate four earnings histories and persist each result without updates."""

    def __init__(
        self,
        financial_query: GetFinancialStatements,
        financial_items: FinancialItemRepository,
        repository: NormalizedEarningsRepository,
    ) -> None:
        self._financial_query = financial_query
        self._financial_items = financial_items
        self._repository = repository

    def execute(
        self, request: NormalizedEarningsRequest
    ) -> tuple[NormalizedEarningsResult, ...]:
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        cutoff = request.as_of.astimezone(UTC)
        if (
            request.valuation_inputs is not None
            and request.valuation_inputs.as_of != cutoff
        ):
            raise DomainValidationError(
                "Valuation inputs and normalized earnings must share the same as_of."
            )
        if (
            request.valuation_inputs is not None
            and request.security_id != request.valuation_inputs.security_id
        ):
            raise DomainValidationError(
                "Normalized earnings and valuation inputs must identify "
                "the same security."
            )
        statements = self._financial_query.execute(
            request.company_id,
            cutoff,
            statement_type=StatementType.PL,
            source_id=request.source_id,
        )
        statements = [
            row for row in statements if row.statement.period_end <= cutoff.date()
        ]
        sources = {row.statement.source_id for row in statements}
        if request.source_id is None and len(sources) > 1:
            raise DomainValidationError(
                "source_id is required when multiple financial sources are eligible."
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

        code_items = {}
        for code in (*_CODE_BY_METRIC.values(), "DEPRECIATION_AMORTIZATION"):
            item = self._financial_items.get_by_code(code)
            if item is not None:
                code_items[code] = item
        records: dict[tuple[int, str], tuple[Decimal, EarningsInputReference]] = {}
        annual_statements = {}
        for result in statements:
            statement = result.statement
            if statement.fiscal_period.value != "FY":
                continue
            if statement.fiscal_year in annual_statements:
                raise DomainValidationError(
                    "Multiple FY statements exist for a fiscal year; select "
                    "one reporting period explicitly."
                )
            annual_statements[statement.fiscal_year] = statement
            lines_by_code = {}
            for line in result.items:
                item = next(
                    (
                        candidate
                        for candidate in code_items.values()
                        if candidate.id == line.financial_item_id
                    ),
                    None,
                )
                if item is not None:
                    lines_by_code[item.item_code] = (line, item)
            for code, (line, item) in lines_by_code.items():
                value = line.value * line.scale_multiplier
                reference = EarningsInputReference(
                    statement_id=statement.id or 0,
                    statement_item_id=line.id or 0,
                    source_id=statement.source_id,
                    revision_number=statement.revision_number,
                    fiscal_year=statement.fiscal_year,
                    fiscal_period=statement.fiscal_period.value,
                    item_code=item.item_code,
                    period_start=statement.period_start or statement.period_end,
                    period_end=statement.period_end,
                    available_at=statement.available_at,
                    publication_date=statement.publication_date,
                    publication_datetime=statement.publication_datetime,
                )
                records[(statement.fiscal_year, code)] = (value, reference)

        observations: dict[EarningsMetric, list[FiscalEarningsObservation]] = {
            metric: [] for metric in EarningsMetric
        }
        for fiscal_year, statement in annual_statements.items():
            period_start = statement.period_start or statement.period_end
            for metric, code in _CODE_BY_METRIC.items():
                record = records.get((fiscal_year, code))
                if record is not None:
                    value, reference = record
                    observations[metric].append(
                        FiscalEarningsObservation(
                            fiscal_year,
                            value,
                            (reference,),
                            period_start,
                            statement.period_end,
                        )
                    )
            op = records.get((fiscal_year, "OPERATING_PROFIT"))
            da = records.get((fiscal_year, "DEPRECIATION_AMORTIZATION"))
            if op is not None and da is not None:
                observations[EarningsMetric.EBITDA].append(
                    FiscalEarningsObservation(
                        fiscal_year,
                        op[0] + da[0],
                        (op[1], da[1]),
                        period_start,
                        statement.period_end,
                    )
                )

        results = [
            analyze_historical_earnings(
                company_id=request.company_id,
                security_id=request.security_id,
                metric=metric,
                observations=tuple(rows),
                window_years=request.window_years,
                method=request.method,
                as_of=cutoff,
            )
            for metric, rows in observations.items()
        ]
        results = self._calculate_normalized_valuations(results, request)
        return tuple(self._repository.create(result) for result in results)

    @staticmethod
    def _calculate_normalized_valuations(
        results: list[NormalizedEarningsResult], request: NormalizedEarningsRequest
    ) -> list[NormalizedEarningsResult]:
        inputs = request.valuation_inputs
        if inputs is None:
            return [
                replace(
                    result,
                    normalized_valuation_status=ValuationResultStatus.INSUFFICIENT_DATA,
                    normalized_valuation_reason=(
                        "Current point-in-time market and balance-sheet inputs "
                        "were not supplied."
                    ),
                    assumptions=result.assumptions
                    + (
                        "Normalized valuation requires current point-in-time market "
                        "and balance-sheet inputs, which were not supplied.",
                    ),
                )
                if result.metric in {EarningsMetric.EPS, EarningsMetric.EBITDA}
                else result
                for result in results
            ]
        definitions = {row.metric_code: row for row in default_metric_definitions()}
        output = []
        for result in results:
            target_code = (
                ValuationMetricCode.PER
                if result.metric == EarningsMetric.EPS
                else ValuationMetricCode.EV_EBITDA
                if result.metric == EarningsMetric.EBITDA
                else None
            )
            if target_code is None:
                output.append(result)
                continue
            if result.status != EarningsResultStatus.AVAILABLE:
                output.append(
                    replace(
                        result,
                        normalized_valuation_status=ValuationResultStatus.INSUFFICIENT_DATA,
                        normalized_valuation_reason=(
                            "Normalized earnings are insufficient for the ratio."
                        ),
                        assumptions=result.assumptions
                        + (
                            "Normalized valuation could not be calculated because "
                            "normalized earnings are insufficient.",
                        ),
                    )
                )
                continue
            earnings_refs = tuple(
                _to_valuation_reference(ref) for ref in result.input_references
            )
            price_refs = tuple(
                ref
                for ref in inputs.input_references
                if ref.record_type == "DAILY_PRICE"
            )
            valuation_refs = (
                price_refs
                + earnings_refs
                + tuple(
                    ref
                    for ref in inputs.input_references
                    if ref.record_type == "FINANCIAL_LINE"
                    and ref.financial_item_code
                    not in {
                        "EPS",
                        "NET_INCOME",
                        "WEIGHTED_AVERAGE_SHARES",
                        "OPERATING_PROFIT",
                        "DEPRECIATION_AMORTIZATION",
                    }
                )
            )
            if result.metric == EarningsMetric.EPS:
                calculation_inputs = replace(
                    inputs,
                    reported_eps=result.normalized_value,
                    net_income=None,
                    weighted_average_shares=None,
                    input_references=valuation_refs,
                )
            else:
                calculation_inputs = replace(
                    inputs,
                    operating_profit=result.normalized_value,
                    depreciation_amortization=Decimal(0),
                    input_references=valuation_refs,
                )
            value = calculate_metric(definitions[target_code], calculation_inputs)
            output.append(
                replace(
                    result,
                    normalized_valuation_status=value.status,
                    normalized_valuation_reason=value.unavailable_reason,
                    normalized_valuation_value=value.value,
                    valuation_input_references=value.input_references,
                )
            )
        return output


def _to_valuation_reference(
    reference: EarningsInputReference,
) -> ValuationInputReference:
    return ValuationInputReference(
        record_type="FINANCIAL_LINE",
        record_id=reference.statement_item_id,
        parent_record_id=reference.statement_id,
        source_id=reference.source_id,
        revision_number=reference.revision_number,
        available_at=reference.available_at,
        financial_item_code=reference.item_code,
        financial_period=reference.fiscal_period,
        period_start=reference.period_start,
        period_end=reference.period_end,
        publication_date=reference.publication_date,
        publication_datetime=reference.publication_datetime,
    )
