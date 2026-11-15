"""Point-in-time orchestration for append-only earnings Cycle Score snapshots."""

from cyclescope.application.dto.cycle_score import (
    CalculateCycleScoreRequest,
    CycleScoreResponse,
)
from cyclescope.application.dto.normalized_earnings import NormalizedEarningsRequest
from cyclescope.application.use_cases.normalized_earnings import (
    CalculateNormalizedEarnings,
)
from cyclescope.domain.entities.cycle_score import (
    CycleScoreInputReference,
    CycleScoreObservation,
)
from cyclescope.domain.entities.normalized_earnings import (
    DepreciationAmortizationSignConvention,
    EarningsMetric,
    EarningsResultStatus,
    NormalizationMethod,
)
from cyclescope.domain.exceptions import DomainValidationError
from cyclescope.domain.repositories.contracts import (
    CycleScoreRepository,
    SecurityRepository,
)
from cyclescope.domain.services.cycle_score import analyze_cycle_score
from cyclescope.domain.value_objects.financial_data import UnitDimension


class CalculateCycleScore:
    """Reuse PIT normalized FY earnings, classify the earnings cycle, and append."""

    def __init__(
        self,
        normalized_earnings: CalculateNormalizedEarnings,
        repository: CycleScoreRepository,
        securities: SecurityRepository,
    ) -> None:
        self._normalized_earnings = normalized_earnings
        self._repository = repository
        self._securities = securities

    def execute(self, request: CalculateCycleScoreRequest) -> CycleScoreResponse:
        if request.security_id is not None:
            security = self._securities.get_by_id(request.security_id)
            if security is None or security.company_id != request.company_id:
                raise DomainValidationError(
                    "The requested security does not belong to the company."
                )
        normalized_results = self._normalized_earnings.execute(
            NormalizedEarningsRequest(
                company_id=request.company_id,
                security_id=request.security_id,
                as_of=request.as_of,
                window_years=request.config.window_years,
                method=NormalizationMethod.ARITHMETIC_MEAN,
                da_sign_convention=DepreciationAmortizationSignConvention.UNKNOWN,
                source_id=request.financial_source_id,
            )
        )
        normalized = next(
            (
                row
                for row in normalized_results
                if row.metric == EarningsMetric.OPERATING_PROFIT
            ),
            None,
        )
        if normalized is None:
            raise DomainValidationError(
                "Normalized earnings service did not return operating profit."
            )
        cutoff = request.as_of
        if (
            normalized.company_id != request.company_id
            or normalized.security_id != request.security_id
            or normalized.as_of != cutoff
            or normalized.metric != EarningsMetric.OPERATING_PROFIT
            or normalized.method != NormalizationMethod.ARITHMETIC_MEAN
            or normalized.requested_window_years != request.config.window_years
            or normalized.unit != UnitDimension.CURRENCY_AMOUNT
            or normalized.calculation_version < 1
        ):
            raise DomainValidationError(
                "Normalized operating-profit result does not match the "
                "Cycle Score request."
            )
        if normalized.status == EarningsResultStatus.UNAVAILABLE:
            raise DomainValidationError(
                "Normalized operating-profit result is unexpectedly unavailable."
            )
        if normalized.id is None:
            raise DomainValidationError(
                "Cycle Score requires a persisted normalized earnings snapshot."
            )

        source_ids = {reference.source_id for reference in normalized.input_references}
        if len(source_ids) > 1:
            raise DomainValidationError(
                "Cycle Score cannot mix financial statement sources."
            )
        selected_source = next(iter(source_ids), request.financial_source_id)
        if (
            request.financial_source_id is not None
            and source_ids
            and source_ids != {request.financial_source_id}
        ):
            raise DomainValidationError(
                "Normalized earnings references do not match the requested source."
            )
        if normalized.currency is None and normalized.fiscal_year_values:
            raise DomainValidationError(
                "Normalized operating-profit observations have no currency."
            )

        observations = []
        for fiscal_year, value in normalized.fiscal_year_values:
            references = tuple(
                reference
                for reference in normalized.input_references
                if reference.fiscal_year == fiscal_year
            )
            if len(references) != 1:
                raise DomainValidationError(
                    "Each annual operating-profit observation must have exactly one "
                    "financial-line reference."
                )
            reference = references[0]
            if (
                reference.fiscal_period != "FY"
                or reference.item_code != "OPERATING_PROFIT"
                or reference.available_at > cutoff
                or reference.period_end > cutoff.date()
            ):
                raise DomainValidationError(
                    "Normalized operating-profit reference violates FY/PIT rules."
                )
            if normalized.currency is None:
                raise DomainValidationError("Operating-profit currency is unavailable.")
            cycle_reference = CycleScoreInputReference(
                record_id=reference.statement_item_id,
                statement_id=reference.statement_id,
                normalized_earnings_result_id=normalized.id or 0,
                source_id=reference.source_id,
                revision_number=reference.revision_number,
                fiscal_year=reference.fiscal_year,
                fiscal_period=reference.fiscal_period,
                item_code=reference.item_code,
                period_end=reference.period_end,
                available_at=reference.available_at,
                period_start=reference.period_start,
                publication_date=reference.publication_date,
                publication_datetime=reference.publication_datetime,
            )
            observations.append(
                CycleScoreObservation(
                    fiscal_year=fiscal_year,
                    value=value,
                    currency=normalized.currency,
                    source_id=reference.source_id,
                    calculation_version=normalized.calculation_version,
                    period_start=reference.period_start,
                    period_end=reference.period_end,
                    references=(cycle_reference,),
                )
            )
        score = analyze_cycle_score(
            company_id=request.company_id,
            security_id=request.security_id,
            as_of=cutoff,
            observations=tuple(observations),
            window_start_fiscal_year=normalized.window_start_fiscal_year,
            window_end_fiscal_year=normalized.window_end_fiscal_year,
            currency=normalized.currency,
            source_id=selected_source,
            normalized_earnings_result_id=normalized.id,
            config=request.config,
        )
        return CycleScoreResponse(self._repository.create(score))
