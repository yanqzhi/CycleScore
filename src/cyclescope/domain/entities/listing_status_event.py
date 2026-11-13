"""Append-only listing status transition history."""

from dataclasses import dataclass
from datetime import date, datetime

from cyclescope.domain.entities.listing import LISTING_STATUSES
from cyclescope.domain.exceptions import DomainValidationError


@dataclass(frozen=True, slots=True)
class ListingStatusEvent:
    listing_id: int
    status: str
    effective_date: date
    id: int | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.listing_id < 1 or self.status not in LISTING_STATUSES:
            raise DomainValidationError("Listing status event is invalid.")
