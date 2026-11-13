"""Immutable financial statement domain entities."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.value_objects.financial_data import (
    ConsolidationScope,
    FiscalPeriod,
    StatementType,
    UnitDimension,
    validate_item_unit,
)


def _utc(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainValidationError(f"{name} must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class FinancialStatement:
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
    source_document_reference: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.statement_type, StatementType):
            raise DomainValidationError("statement_type is invalid.")
        if not isinstance(self.consolidation_scope, ConsolidationScope):
            raise DomainValidationError("consolidation_scope is invalid.")
        if not isinstance(self.fiscal_period, FiscalPeriod):
            raise DomainValidationError("fiscal_period is invalid.")
        if not self.accounting_standard.strip():
            raise DomainValidationError("accounting_standard is required.")
        if self.company_id < 1 or self.source_id < 1 or self.fiscal_year < 1:
            raise DomainValidationError(
                "company, source, and fiscal year must be positive."
            )
        if self.revision_number < 1:
            raise DomainValidationError("revision_number must be positive.")
        if self.period_start is not None and self.period_start > self.period_end:
            raise DomainValidationError("period_start must not follow period_end.")
        if (
            self.statement_type in {StatementType.PL, StatementType.CF}
            and self.period_start is None
        ):
            raise DomainValidationError("PL and CF statements require period_start.")
        if (
            len(self.reporting_currency) != 3
            or not self.reporting_currency.isupper()
            or not self.reporting_currency.isalpha()
        ):
            raise DomainValidationError(
                "reporting_currency must be three uppercase letters."
            )
        object.__setattr__(
            self, "available_at", _utc("available_at", self.available_at)
        )
        object.__setattr__(
            self, "collected_at", _utc("collected_at", self.collected_at)
        )
        if self.publication_datetime is not None:
            object.__setattr__(
                self,
                "publication_datetime",
                _utc("publication_datetime", self.publication_datetime),
            )
        if self.created_at is not None:
            object.__setattr__(self, "created_at", _utc("created_at", self.created_at))
        if self.updated_at is not None:
            object.__setattr__(self, "updated_at", _utc("updated_at", self.updated_at))


@dataclass(frozen=True, slots=True)
class FinancialItem:
    item_code: str
    item_name: str
    statement_type: StatementType
    category: str
    unit_dimension: UnitDimension
    id: int | None = None
    description: str | None = None
    is_active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.statement_type, StatementType) or not isinstance(
            self.unit_dimension, UnitDimension
        ):
            raise DomainValidationError(
                "Financial item type and unit dimension are invalid."
            )
        if (
            not self.item_code.strip()
            or not self.item_name.strip()
            or not self.category.strip()
        ):
            raise DomainValidationError(
                "Financial item code, name, and category are required."
            )


@dataclass(frozen=True, slots=True)
class FinancialStatementItem:
    financial_statement_id: int
    financial_item_id: int
    value: Decimal
    currency_code: str | None
    unit_code: str
    scale_multiplier: int
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def validate_for(self, item: FinancialItem, statement: FinancialStatement) -> None:
        if not isinstance(self.value, Decimal) or not self.value.is_finite():
            raise DomainValidationError("financial value must be a finite Decimal.")
        if (
            not isinstance(self.scale_multiplier, int)
            or isinstance(self.scale_multiplier, bool)
            or self.scale_multiplier < 1
        ):
            raise DomainValidationError("scale_multiplier must be a positive integer.")
        decimal_tuple = self.value.as_tuple()
        if not isinstance(decimal_tuple.exponent, int):
            raise DomainValidationError("Financial value must be finite.")
        fractional_digits = max(-decimal_tuple.exponent, 0)
        integer_digits = max(len(decimal_tuple.digits) - fractional_digits, 0)
        if fractional_digits > 12 or integer_digits > 26:
            raise DomainValidationError(
                "Financial value exceeds NUMERIC(38, 12) precision."
            )
        validate_item_unit(item.unit_dimension, self.unit_code, self.currency_code)
        if item.statement_type != statement.statement_type:
            raise DomainValidationError(
                "Financial item type must match statement type."
            )
        if (
            self.currency_code is not None
            and self.currency_code != statement.reporting_currency
        ):
            raise DomainValidationError(
                "Line currency must match statement reporting currency."
            )


@dataclass(frozen=True, slots=True)
class FinancialItemMapping:
    source_id: int
    source_item_code: str
    source_item_name: str
    financial_item_id: int
    accounting_standard: str | None = None
    id: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.source_id < 1 or self.financial_item_id < 1:
            raise DomainValidationError("Mapping source and item IDs must be positive.")
        if not self.source_item_code.strip() or not self.source_item_name.strip():
            raise DomainValidationError("Source item code and name are required.")
