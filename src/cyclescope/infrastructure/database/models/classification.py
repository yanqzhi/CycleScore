"""SQLAlchemy mappings for external industry classification masters."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from cyclescope.infrastructure.database.base import Base, TimestampMixin


class ClassificationSchemeModel(TimestampMixin, Base):
    __tablename__ = "classification_schemes"
    __table_args__ = (
        UniqueConstraint("scheme_code", name="uq_classification_scheme_code"),
        CheckConstraint("length(trim(scheme_code)) > 0", name="scheme_code_valid"),
        CheckConstraint("length(trim(name)) > 0", name="scheme_name_valid"),
        CheckConstraint("length(trim(publisher)) > 0", name="publisher_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scheme_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(String(160), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ClassificationVersionModel(TimestampMixin, Base):
    __tablename__ = "classification_versions"
    __table_args__ = (
        UniqueConstraint(
            "scheme_id", "version_code", name="uq_classification_version_code"
        ),
        CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="version_effective_range",
        ),
        CheckConstraint("length(trim(version_code)) > 0", name="version_code_valid"),
        Index(
            "ix_classification_versions_scheme_effective",
            "scheme_id",
            "effective_from",
            "effective_to",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scheme_id: Mapped[int] = mapped_column(
        ForeignKey("classification_schemes.id", ondelete="RESTRICT"), nullable=False
    )
    version_code: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class IndustryClassificationMappingModel(TimestampMixin, Base):
    __tablename__ = "industry_classification_mappings"
    __table_args__ = (
        UniqueConstraint(
            "classification_version_id",
            "external_code",
            "valid_from",
            name="uq_classification_mapping_valid_from",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from", name="mapping_validity_range"
        ),
        CheckConstraint(
            "mapping_method IN ('EXACT','MANUAL','APPROXIMATE')",
            name="mapping_method",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name="mapping_confidence_range",
        ),
        CheckConstraint("length(trim(external_code)) > 0", name="external_code_valid"),
        CheckConstraint("length(trim(external_name)) > 0", name="external_name_valid"),
        Index(
            "ix_classification_mapping_lookup",
            "classification_version_id",
            "external_code",
            "valid_from",
            "valid_to",
        ),
        Index("ix_classification_mapping_industry", "internal_industry_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    classification_version_id: Mapped[int] = mapped_column(
        ForeignKey("classification_versions.id", ondelete="RESTRICT"), nullable=False
    )
    external_code: Mapped[str] = mapped_column(String(120), nullable=False)
    external_name: Mapped[str] = mapped_column(String(240), nullable=False)
    internal_industry_id: Mapped[int] = mapped_column(
        ForeignKey("industries.id", ondelete="RESTRICT"), nullable=False
    )
    internal_sub_industry_id: Mapped[int | None] = mapped_column(
        ForeignKey("sub_industries.id", ondelete="RESTRICT")
    )
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    mapping_method: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    notes: Mapped[str | None] = mapped_column(String(1000))
