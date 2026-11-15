"""Provider-neutral classification master commands and query results."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from cyclescope.domain.entities.classification import (
    ClassificationScheme,
    ClassificationVersion,
    IndustryClassificationMapping,
    MappingMethod,
)
from cyclescope.domain.entities.industry import Industry
from cyclescope.domain.entities.sub_industry import SubIndustry


@dataclass(frozen=True, slots=True)
class CreateClassificationSchemeRequest:
    scheme_code: str
    name: str
    publisher: str
    description: str | None = None
    country_code: str | None = None
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class CreateClassificationVersionRequest:
    scheme_id: int
    version_code: str
    effective_from: date
    effective_to: date | None = None
    published_at: datetime | None = None
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class CreateIndustryClassificationMappingRequest:
    classification_version_id: int
    external_code: str
    external_name: str
    internal_industry_id: int
    valid_from: date
    mapping_method: MappingMethod
    internal_sub_industry_id: int | None = None
    valid_to: date | None = None
    confidence: Decimal | None = None
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class ResolveIndustryClassificationRequest:
    scheme_code: str
    version_code: str
    external_code: str
    effective_date: date


@dataclass(frozen=True, slots=True)
class ResolveIndustryClassificationResult:
    mapping: IndustryClassificationMapping
    industry: Industry
    sub_industry: SubIndustry | None


@dataclass(frozen=True, slots=True)
class CreatedClassificationMasterResult:
    scheme: ClassificationScheme | None = None
    version: ClassificationVersion | None = None
    mapping: IndustryClassificationMapping | None = None
