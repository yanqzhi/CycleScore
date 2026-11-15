"""SQLAlchemy adapters for classification schemes, versions, and mappings."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from cyclescope.domain.entities.classification import (
    ClassificationScheme,
    ClassificationVersion,
    IndustryClassificationMapping,
    MappingMethod,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    ClassificationSchemeRepository,
    ClassificationVersionRepository,
    IndustryClassificationMappingRepository,
)
from cyclescope.infrastructure.database.models.classification import (
    ClassificationSchemeModel,
    ClassificationVersionModel,
    IndustryClassificationMappingModel,
)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _scheme(row: ClassificationSchemeModel) -> ClassificationScheme:
    return ClassificationScheme(
        id=row.id,
        scheme_code=row.scheme_code,
        name=row.name,
        description=row.description,
        publisher=row.publisher,
        country_code=row.country_code,
        is_active=row.is_active,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


def _version(row: ClassificationVersionModel) -> ClassificationVersion:
    return ClassificationVersion(
        id=row.id,
        scheme_id=row.scheme_id,
        version_code=row.version_code,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        published_at=_utc(row.published_at),
        is_active=row.is_active,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


def _mapping(row: IndustryClassificationMappingModel) -> IndustryClassificationMapping:
    return IndustryClassificationMapping(
        id=row.id,
        classification_version_id=row.classification_version_id,
        external_code=row.external_code,
        external_name=row.external_name,
        internal_industry_id=row.internal_industry_id,
        internal_sub_industry_id=row.internal_sub_industry_id,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        mapping_method=MappingMethod(row.mapping_method),
        confidence=row.confidence,
        notes=row.notes,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
    )


class SQLAlchemyClassificationSchemeRepository(ClassificationSchemeRepository):
    """Append/read adapter; transaction ownership stays with the caller."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, scheme: ClassificationScheme) -> ClassificationScheme:
        if self.get_by_code(scheme.scheme_code) is not None:
            raise DomainValidationError("Classification scheme code already exists.")
        row = ClassificationSchemeModel(
            scheme_code=scheme.scheme_code,
            name=scheme.name,
            description=scheme.description,
            publisher=scheme.publisher,
            country_code=scheme.country_code,
            is_active=scheme.is_active,
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _scheme(row)

    def get_by_id(self, scheme_id: int) -> ClassificationScheme | None:
        row = self._session.get(ClassificationSchemeModel, scheme_id)
        return _scheme(row) if row is not None else None

    def get_by_code(self, scheme_code: str) -> ClassificationScheme | None:
        row = self._session.scalar(
            select(ClassificationSchemeModel).where(
                ClassificationSchemeModel.scheme_code == scheme_code
            )
        )
        return _scheme(row) if row is not None else None

    def list(self, *, limit: int = 100, offset: int = 0) -> list[ClassificationScheme]:
        rows = self._session.scalars(
            select(ClassificationSchemeModel)
            .order_by(ClassificationSchemeModel.scheme_code)
            .limit(limit)
            .offset(offset)
        )
        return [_scheme(row) for row in rows]


class SQLAlchemyClassificationVersionRepository(ClassificationVersionRepository):
    """Append/read adapter for versioned scheme releases."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(self, version: ClassificationVersion) -> ClassificationVersion:
        if self.get_by_scheme_and_code(version.scheme_id, version.version_code):
            raise DomainValidationError("Classification version code already exists.")
        row = ClassificationVersionModel(
            scheme_id=version.scheme_id,
            version_code=version.version_code,
            effective_from=version.effective_from,
            effective_to=version.effective_to,
            published_at=(
                version.published_at.replace(tzinfo=None)
                if version.published_at
                else None
            ),
            is_active=version.is_active,
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _version(row)

    def get_by_id(self, version_id: int) -> ClassificationVersion | None:
        row = self._session.get(ClassificationVersionModel, version_id)
        return _version(row) if row is not None else None

    def get_by_scheme_and_code(
        self, scheme_id: int, version_code: str
    ) -> ClassificationVersion | None:
        row = self._session.scalar(
            select(ClassificationVersionModel).where(
                ClassificationVersionModel.scheme_id == scheme_id,
                ClassificationVersionModel.version_code == version_code,
            )
        )
        return _version(row) if row is not None else None

    def list_by_scheme(self, scheme_id: int) -> list[ClassificationVersion]:
        rows = self._session.scalars(
            select(ClassificationVersionModel)
            .where(ClassificationVersionModel.scheme_id == scheme_id)
            .order_by(
                ClassificationVersionModel.effective_from,
                ClassificationVersionModel.version_code,
            )
        )
        return [_version(row) for row in rows]


class SQLAlchemyIndustryClassificationMappingRepository(
    IndustryClassificationMappingRepository
):
    """Append/read adapter for immutable effective-dated mappings."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self, mapping: IndustryClassificationMapping
    ) -> IndustryClassificationMapping:
        row = IndustryClassificationMappingModel(
            classification_version_id=mapping.classification_version_id,
            external_code=mapping.external_code,
            external_name=mapping.external_name,
            internal_industry_id=mapping.internal_industry_id,
            internal_sub_industry_id=mapping.internal_sub_industry_id,
            valid_from=mapping.valid_from,
            valid_to=mapping.valid_to,
            mapping_method=mapping.mapping_method.value,
            confidence=mapping.confidence,
            notes=mapping.notes,
        )
        self._session.add(row)
        self._session.flush()
        self._session.refresh(row)
        return _mapping(row)

    def get_by_id(self, mapping_id: int) -> IndustryClassificationMapping | None:
        row = self._session.get(IndustryClassificationMappingModel, mapping_id)
        return _mapping(row) if row is not None else None

    def list_by_version_and_code(
        self, version_id: int, external_code: str
    ) -> list[IndustryClassificationMapping]:
        rows = self._session.scalars(
            select(IndustryClassificationMappingModel)
            .where(
                IndustryClassificationMappingModel.classification_version_id
                == version_id,
                IndustryClassificationMappingModel.external_code == external_code,
            )
            .order_by(
                IndustryClassificationMappingModel.valid_from,
                IndustryClassificationMappingModel.id,
            )
        )
        return [_mapping(row) for row in rows]
