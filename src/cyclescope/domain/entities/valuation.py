"""Provider-neutral valuation metric definitions and calculation values."""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum

from cyclescope.domain.exceptions import DomainValidationError


class ValuationMetricCode(StrEnum):
    PER = "PER"
    PBR = "PBR"
    EV_EBITDA = "EV_EBITDA"
    EPS = "EPS"
    BVPS = "BVPS"
    MARKET_CAPITALIZATION = "MARKET_CAPITALIZATION"
    ENTERPRISE_VALUE = "ENTERPRISE_VALUE"
    EBITDA = "EBITDA"


class ValuationUnit(StrEnum):
    RATIO = "RATIO"
    PER_SHARE = "PER_SHARE"
    CURRENCY_AMOUNT = "CURRENCY_AMOUNT"


class CurrencyApplicability(StrEnum):
    NONE = "NONE"
    MARKET_CURRENCY = "MARKET_CURRENCY"


class ValuationResultStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID_INPUT = "INVALID_INPUT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class ValuationInputReference:
    """Stable reference to one source observation used by a calculation."""

    record_type: str
    record_id: int
    source_id: int
    revision_number: int
    available_at: datetime
    parent_record_id: int | None = None
    observation_date: date | None = None
    financial_item_code: str | None = None
    financial_period: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    publication_date: date | None = None
    publication_datetime: datetime | None = None

    def __post_init__(self) -> None:
        if (
            not self.record_type.strip()
            or min(self.record_id, self.source_id, self.revision_number) < 1
        ):
            raise DomainValidationError("Valuation input reference is invalid.")
        if self.record_type == "DAILY_PRICE":
            if self.parent_record_id is not None or self.observation_date is None:
                raise DomainValidationError("Price input reference is incomplete.")
        elif self.record_type == "FINANCIAL_LINE":
            if (
                self.parent_record_id is None
                or self.parent_record_id < 1
                or not self.financial_item_code
                or self.period_end is None
            ):
                raise DomainValidationError("Financial input reference is incomplete.")
        else:
            raise DomainValidationError("Unsupported valuation input reference type.")
        if self.available_at.tzinfo is None or self.available_at.utcoffset() is None:
            raise DomainValidationError("Input available_at must be timezone-aware.")
        object.__setattr__(self, "available_at", self.available_at.astimezone(UTC))
        if self.publication_datetime is not None:
            if (
                self.publication_datetime.tzinfo is None
                or self.publication_datetime.utcoffset() is None
            ):
                raise DomainValidationError(
                    "Input publication_datetime must be timezone-aware."
                )
            object.__setattr__(
                self,
                "publication_datetime",
                self.publication_datetime.astimezone(UTC),
            )
            if self.publication_datetime > self.available_at:
                raise DomainValidationError(
                    "Input availability cannot precede publication_datetime."
                )


@dataclass(frozen=True, slots=True)
class ValuationMetricDefinition:
    """Versioned definition for one standardized valuation metric."""

    metric_code: ValuationMetricCode
    metric_name: str
    description: str
    unit: ValuationUnit
    currency_applicability: CurrencyApplicability
    required_inputs: tuple[str, ...]
    calculation_method: str
    calculation_version: int = 1
    validity_rules: tuple[str, ...] = ()
    is_active: bool = True
    id: int | None = None

    def __post_init__(self) -> None:
        if not self.metric_name.strip() or not self.description.strip():
            raise DomainValidationError("Metric name and description are required.")
        if not self.required_inputs or len(set(self.required_inputs)) != len(
            self.required_inputs
        ):
            raise DomainValidationError(
                "Metric required_inputs must be non-empty and unique."
            )
        if not self.calculation_method.strip() or self.calculation_version < 1:
            raise DomainValidationError("Metric calculation method/version is invalid.")
        if self.id is not None and self.id < 1:
            raise DomainValidationError("Metric ID must be positive.")


@dataclass(frozen=True, slots=True)
class ValuationInputs:
    """Normalized inputs selected under one PIT cutoff, with source provenance."""

    security_id: int
    observation_date: date
    as_of: datetime
    currency: str | None
    closing_price: Decimal | None = None
    adjusted_closing_price: Decimal | None = None
    reported_eps: Decimal | None = None
    net_income: Decimal | None = None
    total_equity: Decimal | None = None
    cash_and_equivalents: Decimal | None = None
    short_term_debt: Decimal | None = None
    long_term_debt: Decimal | None = None
    operating_profit: Decimal | None = None
    depreciation_amortization: Decimal | None = None
    shares_outstanding: Decimal | None = None
    weighted_average_shares: Decimal | None = None
    eps_calculation_method: str | None = None
    price_source_id: int | None = None
    price_revision_number: int | None = None
    price_observation_id: int | None = None
    price_available_at: datetime | None = None
    financial_statement_ids: tuple[int, ...] = ()
    financial_source_ids: tuple[int, ...] = ()
    financial_statement_available_ats: tuple[datetime, ...] = ()
    financial_period: str | None = None
    input_references: tuple[ValuationInputReference, ...] = ()

    def __post_init__(self) -> None:
        if self.security_id < 1:
            raise DomainValidationError("security_id must be positive.")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
        if self.observation_date != self.as_of.date():
            raise DomainValidationError(
                "Observation date (valuation date) must match the UTC date of as_of."
            )
        if self.price_available_at is not None:
            if (
                self.price_available_at.tzinfo is None
                or self.price_available_at.utcoffset() is None
            ):
                raise DomainValidationError(
                    "price_available_at must be timezone-aware."
                )
            object.__setattr__(
                self, "price_available_at", self.price_available_at.astimezone(UTC)
            )
            if self.price_available_at > self.as_of:
                raise DomainValidationError("Price input is unavailable at as_of.")
        normalized_financial_times = []
        for available_at in self.financial_statement_available_ats:
            if available_at.tzinfo is None or available_at.utcoffset() is None:
                raise DomainValidationError(
                    "Financial statement availability must be timezone-aware."
                )
            normalized = available_at.astimezone(UTC)
            if normalized > self.as_of:
                raise DomainValidationError(
                    "Financial statement input is unavailable at as_of."
                )
            normalized_financial_times.append(normalized)
        object.__setattr__(
            self,
            "financial_statement_available_ats",
            tuple(normalized_financial_times),
        )
        if self.currency is not None and (
            len(self.currency) != 3
            or not self.currency.isalpha()
            or not self.currency.isupper()
        ):
            raise DomainValidationError("currency must be three uppercase letters.")
        for name in (
            "closing_price",
            "adjusted_closing_price",
            "reported_eps",
            "net_income",
            "total_equity",
            "cash_and_equivalents",
            "short_term_debt",
            "long_term_debt",
            "operating_profit",
            "depreciation_amortization",
            "shares_outstanding",
            "weighted_average_shares",
        ):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, Decimal) or not value.is_finite()
            ):
                raise DomainValidationError(
                    f"{name} must be a finite Decimal when present."
                )
        if any(value < 1 for value in self.financial_statement_ids):
            raise DomainValidationError("Financial statement IDs must be positive.")
        if any(value < 1 for value in self.financial_source_ids):
            raise DomainValidationError("Financial source IDs must be positive.")
        if any(
            reference.available_at > self.as_of for reference in self.input_references
        ):
            raise DomainValidationError("An input reference is not available at as_of.")


@dataclass(frozen=True, slots=True)
class ValuationMetricValue:
    """One reproducible, immutable metric result for a security and cutoff."""

    security_id: int
    metric_code: ValuationMetricCode
    observation_date: date
    as_of: datetime
    status: ValuationResultStatus
    value: Decimal | None
    currency: str | None
    unit: ValuationUnit
    financial_period: str | None
    eps_calculation_method: str | None
    calculation_version: int
    price_observation_id: int | None
    price_source_id: int | None
    price_revision_number: int | None
    price_available_at: datetime | None
    financial_statement_ids: tuple[int, ...]
    financial_source_ids: tuple[int, ...]
    financial_statement_available_ats: tuple[datetime, ...]
    input_snapshot: tuple[tuple[str, Decimal], ...] = ()
    unavailable_inputs: tuple[str, ...] = ()
    unavailable_reason: str | None = None
    input_references: tuple[ValuationInputReference, ...] = ()
    created_at: datetime | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        if self.security_id < 1 or self.calculation_version < 1:
            raise DomainValidationError("Metric result identity/version is invalid.")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        object.__setattr__(self, "as_of", self.as_of.astimezone(UTC))
        if self.created_at is not None:
            if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
                raise DomainValidationError("created_at must be timezone-aware.")
            object.__setattr__(self, "created_at", self.created_at.astimezone(UTC))
        if self.price_available_at is not None:
            if (
                self.price_available_at.tzinfo is None
                or self.price_available_at.utcoffset() is None
            ):
                raise DomainValidationError(
                    "price_available_at must be timezone-aware."
                )
            object.__setattr__(
                self, "price_available_at", self.price_available_at.astimezone(UTC)
            )
            if self.price_available_at > self.as_of:
                raise DomainValidationError("Price input is unavailable at as_of.")
        normalized_financial_times = []
        for available_at in self.financial_statement_available_ats:
            if available_at.tzinfo is None or available_at.utcoffset() is None:
                raise DomainValidationError(
                    "Financial statement availability must be timezone-aware."
                )
            normalized = available_at.astimezone(UTC)
            if normalized > self.as_of:
                raise DomainValidationError(
                    "Financial statement input is unavailable at as_of."
                )
            normalized_financial_times.append(normalized)
        object.__setattr__(
            self,
            "financial_statement_available_ats",
            tuple(normalized_financial_times),
        )
        if (self.status == ValuationResultStatus.AVAILABLE) != (self.value is not None):
            raise DomainValidationError(
                "Metric result status conflicts with its value."
            )
        if self.value is not None and not self.value.is_finite():
            raise DomainValidationError("Metric value must be finite.")
        if self.value is not None:
            exponent = self.value.as_tuple().exponent
            if not isinstance(exponent, int):
                raise DomainValidationError("Metric value must be finite.")
            integer_digits = max(len(self.value.as_tuple().digits) + exponent, 0)
            fractional_digits = max(-exponent, 0)
            if integer_digits > 26 or fractional_digits > 12:
                raise DomainValidationError(
                    "Metric value exceeds NUMERIC(38, 12) precision."
                )
        if self.status != ValuationResultStatus.AVAILABLE and not (
            self.unavailable_reason or self.unavailable_inputs
        ):
            raise DomainValidationError(
                "Unavailable results must explain their status."
            )
        if any(not value.is_finite() for _, value in self.input_snapshot):
            raise DomainValidationError("Input snapshot values must be finite.")
