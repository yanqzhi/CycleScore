"""SQLAlchemy mappings for CycleScope master data."""

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cyclescope.infrastructure.database.base import Base, TimestampMixin


class IndustryModel(TimestampMixin, Base):
    """Top-level industry."""

    __tablename__ = "industries"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sub_industries: Mapped[list["SubIndustryModel"]] = relationship(
        back_populates="industry"
    )


class SubIndustryModel(TimestampMixin, Base):
    """Industry subdivision."""

    __tablename__ = "sub_industries"
    __table_args__ = (
        UniqueConstraint("industry_id", "code"),
        Index("ix_sub_industries_industry_id", "industry_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    industry_id: Mapped[int] = mapped_column(
        ForeignKey("industries.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    industry: Mapped[IndustryModel] = relationship(back_populates="sub_industries")


class CompanyModel(TimestampMixin, Base):
    """Issuer or operating company."""

    __tablename__ = "companies"
    __table_args__ = (Index("ix_companies_country_code", "country_code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    fiscal_year_end: Mapped[str | None] = mapped_column(String(5))
    reporting_currency: Mapped[str | None] = mapped_column(String(3))
    listing_status: Mapped[str] = mapped_column(
        String(32), default="listed", nullable=False
    )
    securities: Mapped[list["SecurityModel"]] = relationship(back_populates="company")
    exposures: Mapped[list["CompanyIndustryExposureModel"]] = relationship(
        back_populates="company"
    )


class ExchangeModel(TimestampMixin, Base):
    """Stable exchange and market reference data."""

    __tablename__ = "exchanges"
    id: Mapped[int] = mapped_column(primary_key=True)
    exchange_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    exchange_name: Mapped[str] = mapped_column(String(160), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    market_region: Mapped[str] = mapped_column(String(40), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    currency_code: Mapped[str] = mapped_column(String(3), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class SecurityModel(TimestampMixin, Base):
    """Tradable security listing."""

    __tablename__ = "securities"
    __table_args__ = (Index("ix_securities_company_id", "company_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    security_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    company: Mapped[CompanyModel] = relationship(back_populates="securities")


class SecurityIdentifierModel(TimestampMixin, Base):
    """Typed historical identifiers, stored as text."""

    __tablename__ = "security_identifiers"
    __table_args__ = (
        Index("ix_security_identifiers_security_id", "security_id"),
        Index(
            "ix_security_identifiers_scope",
            "identifier_type",
            "identifier_value",
            "exchange_id",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from",
            name="identifier_validity_range",
        ),
        Index(
            "uq_security_identifier_global_start",
            "identifier_type",
            "identifier_value",
            "valid_from",
            unique=True,
            sqlite_where=text("exchange_id IS NULL"),
            postgresql_where=text("exchange_id IS NULL"),
        ),
        Index(
            "uq_security_identifier_exchange_start",
            "identifier_type",
            "identifier_value",
            "exchange_id",
            "valid_from",
            unique=True,
            sqlite_where=text("exchange_id IS NOT NULL"),
            postgresql_where=text("exchange_id IS NOT NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT"), nullable=False
    )
    identifier_type: Mapped[str] = mapped_column(String(40), nullable=False)
    identifier_value: Mapped[str] = mapped_column(String(120), nullable=False)
    exchange_id: Mapped[int | None] = mapped_column(
        ForeignKey("exchanges.id", ondelete="RESTRICT")
    )
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)


class ListingModel(TimestampMixin, Base):
    """Exchange-specific listing lifecycle history."""

    __tablename__ = "listings"
    __table_args__ = (
        Index("ix_listings_security_id", "security_id"),
        Index("ix_listings_exchange_ticker", "exchange_id", "ticker"),
        UniqueConstraint(
            "exchange_id",
            "ticker",
            "listing_date",
            name="uq_listing_exchange_ticker_start",
        ),
        CheckConstraint(
            "delisting_date IS NULL OR delisting_date >= listing_date",
            name="listing_date_range",
        ),
        CheckConstraint(
            "status IN ('active', 'suspended', 'delisted')", name="listing_status"
        ),
        CheckConstraint(
            "(status = 'delisted' AND delisting_date IS NOT NULL) OR "
            "(status != 'delisted' AND delisting_date IS NULL)",
            name="listing_status_date",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT"), nullable=False
    )
    exchange_id: Mapped[int] = mapped_column(
        ForeignKey("exchanges.id", ondelete="RESTRICT"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    trading_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    listing_date: Mapped[date] = mapped_column(Date, nullable=False)
    delisting_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")


class ListingStatusEventModel(TimestampMixin, Base):
    """Append-only status transition timeline for a listing."""

    __tablename__ = "listing_status_events"
    __table_args__ = (
        UniqueConstraint("listing_id", "effective_date", name="uq_listing_event_date"),
        Index("ix_listing_status_events_listing_id", "listing_id"),
        CheckConstraint(
            "status IN ('active', 'suspended', 'delisted')", name="status_event_status"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)


class LegacyListingReconciliationModel(TimestampMixin, Base):
    """Legacy security listing rows which could not be safely normalized."""

    __tablename__ = "legacy_listing_reconciliation"
    __table_args__ = (
        UniqueConstraint("security_id", name="uq_legacy_listing_security"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    security_id: Mapped[int] = mapped_column(
        ForeignKey("securities.id", ondelete="RESTRICT"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange_code: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    listing_date: Mapped[date | None] = mapped_column(Date)
    delisting_date: Mapped[date | None] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(String(240), nullable=False)


class DataSourceModel(TimestampMixin, Base):
    """Metadata describing a data provider; never contains credentials."""

    __tablename__ = "data_sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(40), nullable=False)
    website: Mapped[str | None] = mapped_column(String(500))
    licensing_type: Mapped[str | None] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    exposures: Mapped[list["CompanyIndustryExposureModel"]] = relationship(
        back_populates="source"
    )


class CompanyIndustryExposureModel(TimestampMixin, Base):
    """Time-bounded revenue exposure connecting companies to sub-industries."""

    __tablename__ = "company_industry_exposures"
    __table_args__ = (
        CheckConstraint(
            "revenue_share >= 0 AND revenue_share <= 1", name="revenue_share_range"
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from",
            name="validity_range",
        ),
        Index("ix_company_industry_exposures_company_id", "company_id"),
        Index("ix_company_industry_exposures_sub_industry_id", "sub_industry_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    sub_industry_id: Mapped[int] = mapped_column(
        ForeignKey("sub_industries.id", ondelete="RESTRICT"), nullable=False
    )
    revenue_share: Mapped[Decimal] = mapped_column(Numeric(8, 7), nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("data_sources.id", ondelete="SET NULL")
    )
    company: Mapped[CompanyModel] = relationship(back_populates="exposures")
    sub_industry: Mapped[SubIndustryModel] = relationship()
    source: Mapped[DataSourceModel | None] = relationship(back_populates="exposures")
