"""Controlled vocabulary for provider-neutral financial data."""

from enum import StrEnum

from cyclescope.domain.exceptions import DomainValidationError


class StatementType(StrEnum):
    BS = "BS"
    PL = "PL"
    CF = "CF"


class ConsolidationScope(StrEnum):
    CONSOLIDATED = "CONSOLIDATED"
    NON_CONSOLIDATED = "NON_CONSOLIDATED"


class FiscalPeriod(StrEnum):
    FY = "FY"
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"
    H1 = "H1"
    NINE_MONTHS = "9M"
    TTM = "TTM"


class UnitDimension(StrEnum):
    CURRENCY_AMOUNT = "CURRENCY_AMOUNT"
    PER_SHARE = "PER_SHARE"
    SHARES = "SHARES"
    PERCENTAGE = "PERCENTAGE"
    RATIO = "RATIO"
    COUNT = "COUNT"


UNIT_CODES: dict[UnitDimension, frozenset[str]] = {
    UnitDimension.CURRENCY_AMOUNT: frozenset({"CURRENCY"}),
    UnitDimension.PER_SHARE: frozenset({"PER_SHARE"}),
    UnitDimension.SHARES: frozenset({"SHARES"}),
    UnitDimension.PERCENTAGE: frozenset({"PERCENTAGE"}),
    UnitDimension.RATIO: frozenset({"RATIO"}),
    UnitDimension.COUNT: frozenset({"COUNT"}),
}


def validate_item_unit(
    dimension: UnitDimension, unit_code: str, currency_code: str | None
) -> None:
    """Require units and optional currency to match a standardized dimension."""
    if unit_code not in UNIT_CODES[dimension]:
        raise DomainValidationError(f"unit_code is invalid for {dimension.value}.")
    currency_bearing = dimension in {
        UnitDimension.CURRENCY_AMOUNT,
        UnitDimension.PER_SHARE,
    }
    if currency_bearing != (currency_code is not None):
        raise DomainValidationError("currency_code does not match the unit dimension.")
    if currency_code is not None and (
        len(currency_code) != 3
        or not currency_code.isalpha()
        or not currency_code.isupper()
    ):
        raise DomainValidationError("currency_code must be three uppercase letters.")
