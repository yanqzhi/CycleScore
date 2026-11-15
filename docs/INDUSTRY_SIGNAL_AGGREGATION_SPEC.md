# Industry Signal Aggregation v1

## Purpose and boundaries

The provider-independent aggregation layer combines normalized Sprint 15 `IndustrySignalObservation` Domain entities. It does not acquire data, mutate observations, infer regions, or calculate Supply & Demand or cycle scores. The Application use case selects PIT-visible observations through existing `GetIndustrySignals`; Domain validates and calculates; Infrastructure persists immutable snapshots and contributor references.

## Versioned policies

The caller selects a policy code and version. Version 1 supports:

| Signal | Policy | Operation |
| --- | --- | --- |
| PRODUCTION, SHIPMENTS, SALES, ORDERS | FLOW_SUM | Sum exact, matching periods |
| INVENTORY | INVENTORY_SUM | Sum explicit scopes on one observation date |
| CAPACITY | CAPACITY_SUM | Sum compatible scopes on one reference date |
| CAPACITY_UTILIZATION | CAPACITY_WEIGHTED_UTILIZATION | Capacity weighted average |

Events (`CAPACITY_ADDITION`, `CAPACITY_CLOSURE_ANNOUNCED`, and `CAPACITY_CLOSURE_COMPLETED`) are rejected. Utilization is only `sum(capacity_i * utilization_i) / sum(capacity_i)` with positive capacity for each included region. Missing capacity is never replaced by an arithmetic mean. Calculations use `Decimal`, retain 12 places, round half-even at the result boundary, and reject results outside `NUMERIC(38, 12)`. At most 100,000 requested contributors are supported; SUM uses a 43-digit context (38 input digits plus five carry digits) to remain exact up to that bound before final output validation.

## Compatibility and region scope

An aggregate names its scope and every constituent region explicitly. Industry, sub-industry, signal, temporal shape, period/date, source, unit, currency, and classification version provenance must match. No source, currency, or unit conversion is inferred. Multiple eligible sources are not merged; callers must select a source or receive the existing query ambiguity behavior.

`CONTAINS` alone proves geographic ancestry. `MEMBER_OF` is accepted for direct economic/market membership of an explicitly selected country; it is never traversed as geographic containment. Constituents are not inferred from either relationship. To conservatively establish non-overlap, multi-constituent aggregates currently accept country nodes only. This permits disjoint country sets while rejecting a continent together with one of its countries. A single explicit broader scope may be aggregated as one observation.

## Point-in-time and revisions

The same UTC-normalized `as_of` is used for measure and capacity acquisition. Only rows with `available_at <= as_of` and an observation date/period end no later than the UTC date of `as_of` contribute. Existing query behavior selects revisions after PIT filtering. `collected_at` is audit metadata only. Historical source IDs, revision numbers, publication metadata, classification references, values, and regions are recorded per contributor.

## Availability, coverage, and confidence

Missing is distinct from zero. A reported null retains its reason; absent PIT observations produce a region-specific reason. `expected_contributor_count` is optional and must be explicitly provided. When absent, coverage and confidence are `NULL`; a result with usable inputs is `PARTIAL`. With an explicit denominator, coverage is included contributor count divided by expected count, stored to seven decimal places. Below the configurable minimum, status is `INSUFFICIENT_DATA` and value is `NULL`; incomplete usable coverage is `PARTIAL`; fully covered input is `AVAILABLE`. Confidence remains unknown in v1 because no validated confidence model exists; it is never copied from coverage.

## Persistence and transaction behavior

Migration `0023_industry_signal_aggregates` adds a snapshot table and contributor table. Recalculation inserts a new snapshot; existing snapshots and observations are not updated or deleted. The repository flushes only. The caller owns commit/rollback, so rollback removes snapshot and contributors together. Downgrade drops only the two new aggregation tables and leaves Sprint 15/16 data untouched.

## Limitations

V1 has four explicit policies and policy version 1 only. Multi-scope overlap outside country-level constituents cannot be proven and is rejected. There is no inferred expected universe, confidence score, currency/unit conversion, event identity, automatic region inference, source blending, or live provider.

## Scope persistence and inactive regions

Each new snapshot stores its aggregate region ID/code and a scope-table entry for the aggregate region plus every explicitly requested constituent, ordered by role and then region code/ID. Missing observations do not remove a requested region from this scope; they remain distinguishable from actual contributors. Retrieval uses saved scope rows and never traverses current relationships. Migration `0024_industry_signal_aggregate_scopes` backfills only known aggregate-region identities for old snapshots. Earlier snapshots did not persist their constituent sets, so those records are marked `scope_complete = false` and their constituent scope is intentionally not inferred.

Inactive regions remain usable when explicitly selected. Region Master has no effective-dated activity history, so the system cannot establish whether a region was active at historical `as_of`; v1 makes no such assumption and records selected IDs as supplied.
