"""SQLAlchemy mappings for standardized financial statements."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from cyclescope.infrastructure.database.base import Base, TimestampMixin


class FinancialStatementModel(TimestampMixin, Base):
    __tablename__ = "financial_statements"
    __table_args__ = (
        CheckConstraint("statement_type IN ('BS','PL','CF')", name="statement_type"),
        CheckConstraint(
            "consolidation_scope IN ('CONSOLIDATED','NON_CONSOLIDATED')",
            name="consolidation_scope",
        ),
        CheckConstraint("revision_number >= 1", name="revision_positive"),
        CheckConstraint(
            "period_start IS NULL OR period_start <= period_end", name="period_range"
        ),
        CheckConstraint(
            "statement_type = 'BS' OR period_start IS NOT NULL",
            name="period_start_required",
        ),
        Index("ix_financial_statements_company_period", "company_id", "period_end"),
        Index(
            "ix_financial_statements_company_type_period",
            "company_id",
            "statement_type",
            "period_end",
        ),
        Index("ix_financial_statements_source_period", "source_id", "period_end"),
        Index("ix_financial_statements_available_at", "available_at"),
        Index(
            "uq_financial_statement_revision_instant",
            "company_id",
            "source_id",
            "statement_type",
            "accounting_standard",
            "consolidation_scope",
            "fiscal_year",
            "fiscal_period",
            "period_end",
            "revision_number",
            unique=True,
            sqlite_where=text("period_start IS NULL"),
            postgresql_where=text("period_start IS NULL"),
        ),
        Index(
            "uq_financial_statement_revision_period",
            "company_id",
            "source_id",
            "statement_type",
            "accounting_standard",
            "consolidation_scope",
            "fiscal_year",
            "fiscal_period",
            "period_end",
            "revision_number",
            "period_start",
            unique=True,
            sqlite_where=text("period_start IS NOT NULL"),
            postgresql_where=text("period_start IS NOT NULL"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
    )
    source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    statement_type: Mapped[str] = mapped_column(String(2), nullable=False)
    accounting_standard: Mapped[str] = mapped_column(String(40), nullable=False)
    consolidation_scope: Mapped[str] = mapped_column(String(24), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    fiscal_period: Mapped[str] = mapped_column(String(4), nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    publication_date: Mapped[date] = mapped_column(Date, nullable=False)
    publication_datetime: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reporting_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    source_document_reference: Mapped[str | None] = mapped_column(String(500))


class FinancialItemModel(TimestampMixin, Base):
    __tablename__ = "financial_items"
    __table_args__ = (
        UniqueConstraint("item_code", name="uq_financial_item_code"),
        CheckConstraint("statement_type IN ('BS','PL','CF')", name="statement_type"),
        CheckConstraint(
            "unit_dimension IN ('CURRENCY_AMOUNT','PER_SHARE','SHARES',"
            "'PERCENTAGE','RATIO','COUNT')",
            name="unit_dimension",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    item_code: Mapped[str] = mapped_column(String(80), nullable=False)
    item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    statement_type: Mapped[str] = mapped_column(String(2), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    unit_dimension: Mapped[str] = mapped_column(String(24), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)


class FinancialStatementItemModel(TimestampMixin, Base):
    __tablename__ = "financial_statement_items"
    __table_args__ = (
        UniqueConstraint(
            "financial_statement_id",
            "financial_item_id",
            name="uq_financial_statement_item",
        ),
        CheckConstraint("scale_multiplier >= 1", name="scale_positive"),
        Index(
            "ix_financial_statement_items_statement",
            "financial_statement_id",
            "financial_item_id",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    financial_statement_id: Mapped[int] = mapped_column(
        ForeignKey("financial_statements.id", ondelete="RESTRICT"), nullable=False
    )
    financial_item_id: Mapped[int] = mapped_column(
        ForeignKey("financial_items.id", ondelete="RESTRICT"), nullable=False
    )
    value: Mapped[Decimal] = mapped_column(Numeric(38, 12), nullable=False)
    currency_code: Mapped[str | None] = mapped_column(String(3))
    unit_code: Mapped[str] = mapped_column(String(24), nullable=False)
    scale_multiplier: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class FinancialItemMappingModel(TimestampMixin, Base):
    __tablename__ = "financial_item_mappings"
    __table_args__ = (
        Index(
            "uq_financial_item_mapping_default",
            "source_id",
            "source_item_code",
            unique=True,
            sqlite_where=text("accounting_standard IS NULL"),
            postgresql_where=text("accounting_standard IS NULL"),
        ),
        Index(
            "uq_financial_item_mapping_standard",
            "source_id",
            "source_item_code",
            "accounting_standard",
            unique=True,
            sqlite_where=text("accounting_standard IS NOT NULL"),
            postgresql_where=text("accounting_standard IS NOT NULL"),
        ),
        Index("ix_financial_item_mapping_code", "source_id", "source_item_code"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    source_item_code: Mapped[str] = mapped_column(String(120), nullable=False)
    source_item_name: Mapped[str] = mapped_column(String(200), nullable=False)
    financial_item_id: Mapped[int] = mapped_column(
        ForeignKey("financial_items.id", ondelete="RESTRICT"), nullable=False
    )
    accounting_standard: Mapped[str | None] = mapped_column(String(40))
