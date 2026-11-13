"""Canonical identifier uniqueness scope rules."""

from dataclasses import dataclass
from enum import StrEnum

from cyclescope.domain.exceptions import DomainValidationError

GLOBAL_IDENTIFIER_TYPES = frozenset({"ISIN"})
EXCHANGE_REQUIRED_IDENTIFIER_TYPES = frozenset(
    {"TICKER", "TRADING_CODE", "EXCHANGE_CODE"}
)


class IdentifierScopeKind(StrEnum):
    GLOBAL = "global"
    EXCHANGE = "exchange"


@dataclass(frozen=True, slots=True)
class IdentifierUniquenessScope:
    """A resolved uniqueness domain for an identifier type and venue."""

    kind: IdentifierScopeKind
    exchange_id: int | None = None


def resolve_identifier_scope(
    identifier_type: str, exchange_id: int | None
) -> IdentifierUniquenessScope:
    """Apply the single canonical mapping from type to uniqueness scope.

    ISIN remains globally unique even when a row also carries an exchange
    annotation. Known trading-code types require a venue. Other types become
    exchange-scoped when a venue is supplied, and global otherwise.
    """
    normalized_type = identifier_type.strip().upper()
    if normalized_type in GLOBAL_IDENTIFIER_TYPES:
        return IdentifierUniquenessScope(IdentifierScopeKind.GLOBAL)
    if normalized_type in EXCHANGE_REQUIRED_IDENTIFIER_TYPES:
        if exchange_id is None:
            raise DomainValidationError(
                f"{normalized_type} identifiers require an exchange scope."
            )
        return IdentifierUniquenessScope(IdentifierScopeKind.EXCHANGE, exchange_id)
    if exchange_id is not None:
        return IdentifierUniquenessScope(IdentifierScopeKind.EXCHANGE, exchange_id)
    return IdentifierUniquenessScope(IdentifierScopeKind.GLOBAL)
