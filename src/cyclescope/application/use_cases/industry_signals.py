"""Industry signal ingestion and point-in-time read use cases."""

from dataclasses import asdict
from datetime import UTC

from cyclescope.application.dto.industry_signal import (
    GetIndustrySignalsRequest,
    GetIndustrySignalsResult,
    ImportIndustrySignalsRequest,
    ImportIndustrySignalsResult,
)
from cyclescope.domain.entities.industry_signal import IndustrySignalObservation
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    DataSourceRepository,
    IndustryRepository,
    IndustrySignalObservationRepository,
    SubIndustryRepository,
)


class ImportIndustrySignals:
    """Validate ownership and append new signal revisions."""

    def __init__(
        self,
        observations: IndustrySignalObservationRepository,
        industries: IndustryRepository,
        sub_industries: SubIndustryRepository,
        sources: DataSourceRepository,
    ) -> None:
        self.observations = observations
        self.industries = industries
        self.sub_industries = sub_industries
        self.sources = sources

    def execute(
        self, request: ImportIndustrySignalsRequest
    ) -> ImportIndustrySignalsResult:
        if not request.observations:
            raise DomainValidationError("At least one industry signal is required.")
        entities = tuple(
            IndustrySignalObservation(**asdict(input_record))
            for input_record in request.observations
        )
        keys = [entity.revision_key for entity in entities]
        if len(keys) != len(set(keys)):
            raise DomainValidationError("Duplicate signal revision in import request.")
        for observation in entities:
            industry = self.industries.get_by_id(observation.industry_id)
            if industry is None:
                raise DomainValidationError("Unknown industry.")
            if observation.sub_industry_id is not None:
                sub_industry = self.sub_industries.get_by_id(
                    observation.sub_industry_id
                )
                if sub_industry is None or sub_industry.industry_id != industry.id:
                    raise DomainValidationError(
                        "Sub-industry does not belong to the selected industry."
                    )
            if self.sources.get_by_id(observation.source_id) is None:
                raise DomainValidationError("Unknown data source.")
            if self.observations.exists_revision(observation):
                raise DomainValidationError("Industry signal revision already exists.")
        stored = tuple(self.observations.create(item) for item in entities)
        return ImportIndustrySignalsResult(stored)


class GetIndustrySignals:
    """Return latest source-scoped signal revisions visible at an instant."""

    def __init__(
        self,
        observations: IndustrySignalObservationRepository,
        industries: IndustryRepository,
        sub_industries: SubIndustryRepository,
    ) -> None:
        self.observations = observations
        self.industries = industries
        self.sub_industries = sub_industries

    def execute(self, request: GetIndustrySignalsRequest) -> GetIndustrySignalsResult:
        if request.as_of.tzinfo is None or request.as_of.utcoffset() is None:
            raise DomainValidationError("as_of must be timezone-aware.")
        if self.industries.get_by_id(request.industry_id) is None:
            raise DomainValidationError("Unknown industry.")
        if request.sub_industry_id is not None:
            sub_industry = self.sub_industries.get_by_id(request.sub_industry_id)
            if sub_industry is None or sub_industry.industry_id != request.industry_id:
                raise DomainValidationError(
                    "Sub-industry does not belong to the selected industry."
                )
        as_of = request.as_of.astimezone(UTC)
        rows = self.observations.list_available_as_of(
            request.industry_id,
            as_of,
            signal_type=request.signal_type,
            sub_industry_id=request.sub_industry_id,
            region_code=request.region_code,
            source_id=request.source_id,
        )
        visible: dict[tuple[object, ...], IndustrySignalObservation] = {}
        for row in rows:
            temporal_end = row.period_end or row.observation_date
            if row.available_at > as_of or temporal_end is None:
                continue
            if temporal_end > as_of.date():
                continue
            old = visible.get(row.observation_key)
            if old is None or (
                row.revision_number,
                row.available_at,
                row.id or 0,
            ) > (
                old.revision_number,
                old.available_at,
                old.id or 0,
            ):
                visible[row.observation_key] = row
        selected = tuple(
            sorted(
                visible.values(),
                key=lambda row: (
                    row.period_end or row.observation_date or row.publication_date,
                    row.signal_type.value,
                    row.sub_industry_id or 0,
                    row.region_code,
                    row.source_id,
                ),
            )
        )
        if request.source_id is None and len({row.source_id for row in selected}) > 1:
            raise DomainValidationError(
                "source_id is required when multiple industry signal sources "
                "are eligible."
            )
        return GetIndustrySignalsResult(selected)
