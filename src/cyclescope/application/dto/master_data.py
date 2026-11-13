"""Typed application requests for issuer, venue, identity, listing, and exposure."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class CompanyInput:
    name: str
    country_code: str
    fiscal_year_end: str | None = None
    reporting_currency: str | None = None
    listing_status: str = "listed"


@dataclass(frozen=True, slots=True)
class SecurityInput:
    company_id: int
    security_type: str
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class ExchangeInput:
    exchange_code: str
    exchange_name: str
    country_code: str
    market_region: str
    timezone: str
    currency_code: str
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class SecurityIdentifierInput:
    security_id: int
    identifier_type: str
    identifier_value: str
    valid_from: date
    exchange_id: int | None = None
    valid_to: date | None = None


@dataclass(frozen=True, slots=True)
class ListingInput:
    security_id: int
    exchange_id: int
    ticker: str
    trading_currency: str
    listing_date: date
    delisting_date: date | None = None
    status: str = "active"


@dataclass(frozen=True, slots=True)
class ListingStatusInput:
    listing_id: int
    status: str
    effective_date: date


@dataclass(frozen=True, slots=True)
class CompanyIndustryExposureInput:
    company_id: int
    sub_industry_id: int
    revenue_share: Decimal
    valid_from: date | None = None
    valid_to: date | None = None
    source_id: int | None = None
