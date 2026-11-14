"""Requests for historical normalized earnings calculations."""

from dataclasses import dataclass
from datetime import datetime

from cyclescope.domain.entities.normalized_earnings import NormalizationMethod
from cyclescope.domain.entities.valuation import ValuationInputs


@dataclass(frozen=True, slots=True)
class NormalizedEarningsRequest:
    company_id: int
    as_of: datetime
    window_years: int
    method: NormalizationMethod
    source_id: int | None = None
    security_id: int | None = None
    valuation_inputs: ValuationInputs | None = None
