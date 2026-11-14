"""Deterministic valuation calculations over normalized, point-in-time inputs."""

from collections.abc import Callable
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext

from cyclescope.domain.entities.valuation import (
    CurrencyApplicability,
    ValuationInputs,
    ValuationMetricCode,
    ValuationMetricDefinition,
    ValuationMetricValue,
    ValuationResultStatus,
    ValuationUnit,
)
from cyclescope.domain.exceptions import DomainValidationError

_DEFINITIONS = (
    ValuationMetricDefinition(
        ValuationMetricCode.PER,
        "Price to Earnings Ratio",
        "Closing share price divided by earnings per share.",
        ValuationUnit.RATIO,
        CurrencyApplicability.NONE,
        ("closing_price", "reported_eps or net_income and weighted_average_shares"),
        "price_to_earnings",
        validity_rules=("earnings_per_share > 0",),
    ),
    ValuationMetricDefinition(
        ValuationMetricCode.PBR,
        "Price to Book Ratio",
        "Closing share price divided by book value per share.",
        ValuationUnit.RATIO,
        CurrencyApplicability.NONE,
        ("closing_price", "total_equity", "shares_outstanding"),
        "price_to_book",
        validity_rules=("book_value_per_share > 0",),
    ),
    ValuationMetricDefinition(
        ValuationMetricCode.EV_EBITDA,
        "Enterprise Value to EBITDA",
        "Enterprise value divided by EBITDA.",
        ValuationUnit.RATIO,
        CurrencyApplicability.NONE,
        (
            "closing_price",
            "shares_outstanding",
            "short_term_debt",
            "long_term_debt",
            "cash_and_equivalents",
            "EBITDA",
        ),
        "ev_to_ebitda",
        validity_rules=("EBITDA > 0",),
    ),
    ValuationMetricDefinition(
        ValuationMetricCode.EPS,
        "Earnings Per Share",
        "Reported EPS, or net income divided by weighted average shares.",
        ValuationUnit.PER_SHARE,
        CurrencyApplicability.MARKET_CURRENCY,
        ("reported_eps or net_income and weighted_average_shares",),
        "earnings_per_share",
    ),
    ValuationMetricDefinition(
        ValuationMetricCode.BVPS,
        "Book Value Per Share",
        "Total equity divided by shares outstanding.",
        ValuationUnit.PER_SHARE,
        CurrencyApplicability.MARKET_CURRENCY,
        ("total_equity", "shares_outstanding"),
        "book_value_per_share",
    ),
    ValuationMetricDefinition(
        ValuationMetricCode.MARKET_CAPITALIZATION,
        "Market Capitalization",
        "Closing share price multiplied by shares outstanding.",
        ValuationUnit.CURRENCY_AMOUNT,
        CurrencyApplicability.MARKET_CURRENCY,
        ("closing_price", "shares_outstanding"),
        "market_capitalization",
    ),
    ValuationMetricDefinition(
        ValuationMetricCode.ENTERPRISE_VALUE,
        "Enterprise Value",
        "Market capitalization plus debt less cash and cash equivalents.",
        ValuationUnit.CURRENCY_AMOUNT,
        CurrencyApplicability.MARKET_CURRENCY,
        (
            "closing_price",
            "shares_outstanding",
            "short_term_debt",
            "long_term_debt",
            "cash_and_equivalents",
        ),
        "enterprise_value",
    ),
    ValuationMetricDefinition(
        ValuationMetricCode.EBITDA,
        "EBITDA",
        "Operating profit plus depreciation and amortization.",
        ValuationUnit.CURRENCY_AMOUNT,
        CurrencyApplicability.MARKET_CURRENCY,
        ("operating_profit", "depreciation_amortization"),
        "ebitda",
    ),
)
_VALUATION_QUANTUM = Decimal("0.000000000001")


def default_metric_definitions() -> tuple[ValuationMetricDefinition, ...]:
    """Return the versioned initial metric master definitions."""
    return _DEFINITIONS


def calculate_metric(
    definition: ValuationMetricDefinition, inputs: ValuationInputs
) -> ValuationMetricValue:
    """Calculate one metric; absent inputs are explicit and never treated as zero."""
    methods: dict[
        str,
        Callable[[ValuationInputs], tuple[Decimal | None, list[str], list[str]]],
    ] = {
        "price_to_earnings": _per,
        "price_to_book": _pbr,
        "ev_to_ebitda": _ev_ebitda,
        "earnings_per_share": _eps,
        "book_value_per_share": _bvps,
        "market_capitalization": _market_cap,
        "enterprise_value": _enterprise_value,
        "ebitda": _ebitda,
    }
    method = methods.get(definition.calculation_method)
    if method is None:
        raise DomainValidationError(
            f"Unsupported calculation method: {definition.calculation_method}."
        )
    value, missing, invalid = method(inputs)
    if value is not None:
        try:
            with localcontext() as context:
                context.prec = 50
                value = value.quantize(_VALUATION_QUANTUM, rounding=ROUND_HALF_EVEN)
        except InvalidOperation as exc:
            raise DomainValidationError(
                "Metric value exceeds NUMERIC(38, 12) precision."
            ) from exc
    status = ValuationResultStatus.AVAILABLE
    if any(value.startswith("INVALID_INPUT:") for value in invalid):
        status = ValuationResultStatus.INVALID_INPUT
    elif any(value.startswith("NOT_APPLICABLE:") for value in invalid):
        status = ValuationResultStatus.NOT_APPLICABLE
    elif missing:
        status = ValuationResultStatus.INSUFFICIENT_DATA
    issues = [value.split(":", 1)[-1].strip() for value in (*missing, *invalid)]
    fields, financial_codes, uses_price = _metric_dependencies(
        definition.metric_code, inputs
    )
    references = tuple(
        reference
        for reference in inputs.input_references
        if (
            reference.record_type == "DAILY_PRICE"
            and uses_price
            or reference.record_type == "FINANCIAL_LINE"
            and reference.financial_item_code in financial_codes
        )
    )
    financial_references = tuple(
        reference
        for reference in references
        if reference.record_type == "FINANCIAL_LINE"
    )
    price_reference = next(
        (
            reference
            for reference in references
            if reference.record_type == "DAILY_PRICE"
        ),
        None,
    )
    return ValuationMetricValue(
        security_id=inputs.security_id,
        metric_code=definition.metric_code,
        observation_date=inputs.observation_date,
        as_of=inputs.as_of,
        status=status,
        value=value,
        currency=(
            inputs.currency
            if definition.currency_applicability
            == CurrencyApplicability.MARKET_CURRENCY
            else None
        ),
        unit=definition.unit,
        financial_period=inputs.financial_period,
        eps_calculation_method=(
            (
                inputs.eps_calculation_method
                or (
                    "REPORTED"
                    if inputs.reported_eps is not None
                    else "DERIVED_NET_INCOME_OVER_WEIGHTED_SHARES"
                    if inputs.net_income is not None
                    and inputs.weighted_average_shares is not None
                    else None
                )
            )
            if definition.metric_code
            in {ValuationMetricCode.EPS, ValuationMetricCode.PER}
            else None
        ),
        calculation_version=definition.calculation_version,
        price_observation_id=(
            price_reference.record_id
            if price_reference
            else inputs.price_observation_id
            if uses_price
            else None
        ),
        price_source_id=(
            price_reference.source_id
            if price_reference
            else inputs.price_source_id
            if uses_price
            else None
        ),
        price_revision_number=(
            price_reference.revision_number
            if price_reference
            else inputs.price_revision_number
            if uses_price
            else None
        ),
        price_available_at=(
            price_reference.available_at
            if price_reference
            else inputs.price_available_at
            if uses_price
            else None
        ),
        financial_statement_ids=tuple(
            sorted(
                {
                    reference.parent_record_id
                    for reference in financial_references
                    if reference.parent_record_id is not None
                }
            )
        ),
        financial_source_ids=tuple(
            sorted({reference.source_id for reference in financial_references})
        ),
        financial_statement_available_ats=tuple(
            sorted({reference.available_at for reference in financial_references})
        ),
        input_snapshot=tuple(
            (name, value)
            for name in fields
            if (value := getattr(inputs, name)) is not None
        ),
        unavailable_inputs=tuple(issues),
        unavailable_reason="; ".join(issues) if issues else None,
        input_references=references,
    )


def _metric_dependencies(
    code: ValuationMetricCode, inputs: ValuationInputs
) -> tuple[tuple[str, ...], frozenset[str], bool]:
    """Return normalized input fields and source-line codes used by a metric."""
    eps_fields = (
        ("reported_eps",)
        if inputs.reported_eps is not None
        else ("net_income", "weighted_average_shares")
    )
    eps_codes = (
        frozenset({"EPS"})
        if inputs.reported_eps is not None
        else frozenset({"NET_INCOME", "WEIGHTED_AVERAGE_SHARES"})
    )
    dependencies = {
        ValuationMetricCode.EPS: (eps_fields, eps_codes, False),
        ValuationMetricCode.PER: (("closing_price", *eps_fields), eps_codes, True),
        ValuationMetricCode.PBR: (
            ("closing_price", "total_equity", "shares_outstanding"),
            frozenset({"TOTAL_EQUITY", "SHARES_OUTSTANDING"}),
            True,
        ),
        ValuationMetricCode.BVPS: (
            ("total_equity", "shares_outstanding"),
            frozenset({"TOTAL_EQUITY", "SHARES_OUTSTANDING"}),
            False,
        ),
        ValuationMetricCode.MARKET_CAPITALIZATION: (
            ("closing_price", "shares_outstanding"),
            frozenset({"SHARES_OUTSTANDING"}),
            True,
        ),
        ValuationMetricCode.ENTERPRISE_VALUE: (
            (
                "closing_price",
                "shares_outstanding",
                "short_term_debt",
                "long_term_debt",
                "cash_and_equivalents",
            ),
            frozenset(
                {
                    "SHARES_OUTSTANDING",
                    "SHORT_TERM_DEBT",
                    "LONG_TERM_DEBT",
                    "CASH_AND_CASH_EQUIVALENTS",
                }
            ),
            True,
        ),
        ValuationMetricCode.EBITDA: (
            ("operating_profit", "depreciation_amortization"),
            frozenset({"OPERATING_PROFIT", "DEPRECIATION_AMORTIZATION"}),
            False,
        ),
        ValuationMetricCode.EV_EBITDA: (
            (
                "closing_price",
                "shares_outstanding",
                "short_term_debt",
                "long_term_debt",
                "cash_and_equivalents",
                "operating_profit",
                "depreciation_amortization",
            ),
            frozenset(
                {
                    "SHARES_OUTSTANDING",
                    "SHORT_TERM_DEBT",
                    "LONG_TERM_DEBT",
                    "CASH_AND_CASH_EQUIVALENTS",
                    "OPERATING_PROFIT",
                    "DEPRECIATION_AMORTIZATION",
                }
            ),
            True,
        ),
    }
    return dependencies[code]


def _resolve(*values: tuple[str, Decimal | None]) -> tuple[list[Decimal], list[str]]:
    present, missing = [], []
    for name, value in values:
        if value is None:
            missing.append(name)
        else:
            present.append(value)
    return present, missing


def _calc(
    values: tuple[tuple[str, Decimal | None], ...],
    operation: Callable[..., Decimal],
    *,
    positive_input: str | None = None,
) -> tuple[Decimal | None, list[str], list[str]]:
    present, missing = _resolve(*values)
    if missing:
        return None, missing, []
    if positive_input is not None:
        values_by_name = dict(values)
        divisor = values_by_name.get(positive_input)
        if divisor is None:
            raise DomainValidationError(
                f"Positive input {positive_input!r} is not in this calculation."
            )
        if divisor <= 0:
            return None, [], [f"INVALID_INPUT: {positive_input} must be positive."]
    return operation(*present), [], []


def _eps(i: ValuationInputs) -> tuple[Decimal | None, list[str], list[str]]:
    if i.reported_eps is not None:
        return i.reported_eps, [], []
    return _calc(
        (
            ("net_income", i.net_income),
            ("weighted_average_shares", i.weighted_average_shares),
        ),
        lambda earnings, shares: earnings / shares,
        positive_input="weighted_average_shares",
    )


def _bvps(i: ValuationInputs) -> tuple[Decimal | None, list[str], list[str]]:
    return _calc(
        (
            ("total_equity", i.total_equity),
            ("shares_outstanding", i.shares_outstanding),
        ),
        lambda equity, shares: equity / shares,
        positive_input="shares_outstanding",
    )


def _market_cap(i: ValuationInputs) -> tuple[Decimal | None, list[str], list[str]]:
    return _calc(
        (
            ("closing_price", i.closing_price),
            ("shares_outstanding", i.shares_outstanding),
        ),
        lambda price, shares: price * shares,
        positive_input="shares_outstanding",
    )


def _enterprise_value(
    i: ValuationInputs,
) -> tuple[Decimal | None, list[str], list[str]]:
    return _calc(
        (
            ("closing_price", i.closing_price),
            ("shares_outstanding", i.shares_outstanding),
            ("short_term_debt", i.short_term_debt),
            ("long_term_debt", i.long_term_debt),
            ("cash_and_equivalents", i.cash_and_equivalents),
        ),
        lambda price, shares, short_debt, long_debt, cash: (
            price * shares + short_debt + long_debt - cash
        ),
        positive_input="shares_outstanding",
    )


def _ebitda(i: ValuationInputs) -> tuple[Decimal | None, list[str], list[str]]:
    return _calc(
        (
            ("operating_profit", i.operating_profit),
            ("depreciation_amortization", i.depreciation_amortization),
        ),
        lambda operating, da: operating + da,
    )


def _per(i: ValuationInputs) -> tuple[Decimal | None, list[str], list[str]]:
    eps, missing, invalid = _eps(i)
    if missing or invalid:
        return None, missing or ["earnings_per_share"], invalid
    assert eps is not None
    if eps <= 0:
        return (
            None,
            [],
            [
                "NOT_APPLICABLE: non-positive EPS identifies a loss-making period; "
                "conventional PER is not meaningful."
            ],
        )
    return _calc(
        (("closing_price", i.closing_price), ("earnings_per_share", eps)),
        lambda price, earnings: price / earnings,
    )


def _pbr(i: ValuationInputs) -> tuple[Decimal | None, list[str], list[str]]:
    bvps, missing, invalid = _bvps(i)
    if missing or invalid:
        return None, missing or ["book_value_per_share"], invalid
    assert bvps is not None
    if bvps <= 0:
        return (
            None,
            [],
            [
                "NOT_APPLICABLE: conventional PBR requires positive book value "
                "per share."
            ],
        )
    return _calc(
        (("closing_price", i.closing_price), ("book_value_per_share", bvps)),
        lambda price, book: price / book,
    )


def _ev_ebitda(i: ValuationInputs) -> tuple[Decimal | None, list[str], list[str]]:
    ev, missing, invalid = _enterprise_value(i)
    ebitda, ebitda_missing, ebitda_invalid = _ebitda(i)
    if missing or ebitda_missing:
        return None, missing + ebitda_missing, []
    if invalid or ebitda_invalid or ebitda is None or ebitda <= 0:
        return (
            None,
            [],
            invalid
            + ebitda_invalid
            + ["NOT_APPLICABLE: conventional EV/EBITDA requires positive EBITDA."],
        )
    assert ev is not None
    return ev / ebitda, [], []
