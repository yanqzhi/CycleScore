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


class SecurityModel(TimestampMixin, Base):
    """Tradable security listing."""

    __tablename__ = "securities"
    __table_args__ = (
        UniqueConstraint("exchange", "ticker", name="uq_securities_exchange_ticker"),
        Index("ix_securities_company_id", "company_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    security_type: Mapped[str] = mapped_column(String(32), nullable=False)
    listing_date: Mapped[date | None] = mapped_column(Date)
    delisting_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    company: Mapped[CompanyModel] = relationship(back_populates="securities")


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
