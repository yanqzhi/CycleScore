"""Small market-data value objects."""

import re
from dataclasses import dataclass
from datetime import date, datetime

from cyclescope.domain.exceptions import DomainValidationError

_CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")


def validate_currency_code(value: str) -> None:
    """Require a normalized three-letter uppercase currency code."""
    if not _CURRENCY_PATTERN.fullmatch(value):
        raise DomainValidationError(
            f"Currency code {value!r} must contain three uppercase letters."
        )


@dataclass(frozen=True, slots=True)
class CurrencyPair:
    """An ordered FX pair, quoted as units of quote per base currency."""

    base_currency: str
    quote_currency: str

    def __post_init__(self) -> None:
        validate_currency_code(self.base_currency)
        validate_currency_code(self.quote_currency)
        if self.base_currency == self.quote_currency:
            raise DomainValidationError("Base and quote currencies must be different.")


@dataclass(frozen=True, slots=True)
class MarketDataPeriod:
    """Inclusive range of exchange-local observation dates."""

    start_date: date
    end_date: date

    def __post_init__(self) -> None:
        if (
            isinstance(self.start_date, datetime)
            or not isinstance(self.start_date, date)
            or isinstance(self.end_date, datetime)
            or not isinstance(self.end_date, date)
        ):
            raise DomainValidationError(
                "Market data period bounds must be calendar dates."
            )
        if self.start_date > self.end_date:
            raise DomainValidationError("start_date must be on or before end_date.")
