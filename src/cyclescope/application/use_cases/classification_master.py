"""Registration and historical resolution of industry classifications."""

from datetime import date

from cyclescope.application.dto.classification import (
    CreateClassificationSchemeRequest,
    CreateClassificationVersionRequest,
    CreatedClassificationMasterResult,
    CreateIndustryClassificationMappingRequest,
    ResolveIndustryClassificationRequest,
    ResolveIndustryClassificationResult,
)
from cyclescope.domain.entities.classification import (
    ClassificationScheme,
    ClassificationVersion,
    IndustryClassificationMapping,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    ClassificationSchemeRepository,
    ClassificationVersionRepository,
    IndustryClassificationMappingRepository,
    IndustryRepository,
    SubIndustryRepository,
)


def _overlaps(
    start_a: date, end_a: date | None, start_b: date, end_b: date | None
) -> bool:
    return (end_a is None or start_b <= end_a) and (end_b is None or start_a <= end_b)


class RegisterClassificationScheme:
    def __init__(self, schemes: ClassificationSchemeRepository) -> None:
        self.schemes = schemes

    def execute(
        self, request: CreateClassificationSchemeRequest
    ) -> CreatedClassificationMasterResult:
        if self.schemes.get_by_code(request.scheme_code) is not None:
            raise DomainValidationError("Classification scheme code already exists.")
        scheme = self.schemes.create(
            ClassificationScheme(
                scheme_code=request.scheme_code,
                name=request.name,
                publisher=request.publisher,
                description=request.description,
                country_code=request.country_code,
                is_active=request.is_active,
            )
        )
        return CreatedClassificationMasterResult(scheme=scheme)


class RegisterClassificationVersion:
    def __init__(
        self,
        schemes: ClassificationSchemeRepository,
        versions: ClassificationVersionRepository,
    ) -> None:
        self.schemes, self.versions = schemes, versions

    def execute(
        self, request: CreateClassificationVersionRequest
    ) -> CreatedClassificationMasterResult:
        if self.schemes.get_by_id(request.scheme_id) is None:
            raise DomainValidationError("Unknown classification scheme.")
        version = ClassificationVersion(
            scheme_id=request.scheme_id,
            version_code=request.version_code,
            effective_from=request.effective_from,
            effective_to=request.effective_to,
            published_at=request.published_at,
            is_active=request.is_active,
        )
        if (
            self.versions.get_by_scheme_and_code(
                version.scheme_id, version.version_code
            )
            is not None
        ):
            raise DomainValidationError("Classification version code already exists.")
        for existing in self.versions.list_by_scheme(version.scheme_id):
            if _overlaps(
                version.effective_from,
                version.effective_to,
                existing.effective_from,
                existing.effective_to,
            ):
                raise DomainValidationError(
                    "Classification version effective intervals cannot overlap."
                )
        return CreatedClassificationMasterResult(version=self.versions.create(version))


class RegisterIndustryClassificationMapping:
    def __init__(
        self,
        mappings: IndustryClassificationMappingRepository,
        versions: ClassificationVersionRepository,
        industries: IndustryRepository,
        sub_industries: SubIndustryRepository,
    ) -> None:
        self.mappings = mappings
        self.versions = versions
        self.industries = industries
        self.sub_industries = sub_industries

    def execute(
        self, request: CreateIndustryClassificationMappingRequest
    ) -> CreatedClassificationMasterResult:
        version = self.versions.get_by_id(request.classification_version_id)
        if version is None:
            raise DomainValidationError("Unknown classification version.")
        industry = self.industries.get_by_id(request.internal_industry_id)
        if industry is None:
            raise DomainValidationError("Unknown internal industry.")
        if request.internal_sub_industry_id is not None:
            sub_industry = self.sub_industries.get_by_id(
                request.internal_sub_industry_id
            )
            if sub_industry is None or sub_industry.industry_id != industry.id:
                raise DomainValidationError(
                    "Sub-industry does not belong to the selected industry."
                )
        mapping = IndustryClassificationMapping(
            classification_version_id=request.classification_version_id,
            external_code=request.external_code,
            external_name=request.external_name,
            internal_industry_id=request.internal_industry_id,
            internal_sub_industry_id=request.internal_sub_industry_id,
            valid_from=request.valid_from,
            valid_to=request.valid_to,
            mapping_method=request.mapping_method,
            confidence=request.confidence,
            notes=request.notes,
        )
        if mapping.valid_from < version.effective_from or (
            version.effective_to is not None
            and (mapping.valid_to is None or mapping.valid_to > version.effective_to)
        ):
            raise DomainValidationError(
                "Mapping validity must be contained in its version's effective period."
            )
        existing_mappings = self.mappings.list_by_version_and_code(
            mapping.classification_version_id, mapping.external_code
        )
        if any(
            _overlaps(
                mapping.valid_from,
                mapping.valid_to,
                item.valid_from,
                item.valid_to,
            )
            for item in existing_mappings
        ):
            raise DomainValidationError(
                "Mapping validity overlaps an existing mapping for this code/version."
            )
        return CreatedClassificationMasterResult(mapping=self.mappings.create(mapping))


class ResolveIndustryClassification:
    """Resolve one exact scheme/version/code on its effective date."""

    def __init__(
        self,
        schemes: ClassificationSchemeRepository,
        versions: ClassificationVersionRepository,
        mappings: IndustryClassificationMappingRepository,
        industries: IndustryRepository,
        sub_industries: SubIndustryRepository,
    ) -> None:
        self.schemes = schemes
        self.versions = versions
        self.mappings = mappings
        self.industries = industries
        self.sub_industries = sub_industries

    def execute(
        self, request: ResolveIndustryClassificationRequest
    ) -> ResolveIndustryClassificationResult:
        scheme = self.schemes.get_by_code(request.scheme_code)
        if scheme is None:
            raise DomainValidationError("Unknown classification scheme.")
        version = self.versions.get_by_scheme_and_code(
            scheme.id or 0, request.version_code
        )
        if version is None:
            raise DomainValidationError("Unknown classification version.")
        if not version.is_effective_on(request.effective_date):
            raise DomainValidationError(
                "Effective date is outside the classification version period."
            )
        eligible = [
            item
            for item in self.mappings.list_by_version_and_code(
                version.id or 0, request.external_code
            )
            if item.is_valid_on(request.effective_date)
        ]
        if not eligible:
            raise DomainValidationError(
                "No mapping exists for this code on the effective date."
            )
        if len(eligible) != 1:
            raise DomainValidationError(
                "Classification mapping is ambiguous for the effective date."
            )
        mapping = eligible[0]
        industry = self.industries.get_by_id(mapping.internal_industry_id)
        if industry is None:
            raise DomainValidationError("Mapped internal industry no longer exists.")
        sub_industry = (
            self.sub_industries.get_by_id(mapping.internal_sub_industry_id)
            if mapping.internal_sub_industry_id is not None
            else None
        )
        if mapping.internal_sub_industry_id is not None and (
            sub_industry is None or sub_industry.industry_id != industry.id
        ):
            raise DomainValidationError("Mapped sub-industry relationship is invalid.")
        return ResolveIndustryClassificationResult(mapping, industry, sub_industry)
