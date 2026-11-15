# Industry Signal Data Foundation v1

## Scope

This foundation stores provider-neutral industry observations and supports
ingestion and point-in-time retrieval. It does not aggregate signals or calculate
inventory, supply-demand, capacity, or cycle scores. It never converts units or
currencies and never estimates industry data from company revenue exposure.

## Signal types and time shapes

Each signal type has one temporal shape, derived by the Domain taxonomy:

| Signal types | Shape | Required date fields |
| --- | --- | --- |
| `INVENTORY`, `CAPACITY`, `CAPACITY_UTILIZATION` | Point observation | `observation_date` |
| `PRODUCTION`, `SHIPMENTS`, `SALES`, `ORDERS` | Period observation | `period_start`, `period_end` |
| `CAPACITY_ADDITION`, `CAPACITY_CLOSURE_ANNOUNCED`, `CAPACITY_CLOSURE_COMPLETED` | Event | `observation_date` |

Point and event records cannot carry period boundaries. Period records cannot
carry an observation date and require an ordered inclusive date range. Announced
and completed closures remain separate signal types, even when they concern the
same facility and date. `CAPACITY_ADDITION` is stored as an event because it
records a discrete commissioning event; later inventory or capacity levels are
separate observations.

## Units, currencies, and missing values

Units use the controlled codes `TONNE`, `THOUSAND_TONNE`, `UNIT`,
`THOUSAND_UNITS`, `CURRENCY`, `PERCENTAGE`, and `INDEX`. Production, shipments,
capacity, additions, and closure quantities use physical units. Inventory,
sales, and orders may use physical units, currency, or an index. Capacity
utilization uses percentages from 0 through 100. Currency values require a
three-letter uppercase currency code; other units forbid a currency code.
Values are finite `Decimal` values bounded to `NUMERIC(38, 12)` precision.
No conversion or scaling is applied: `TONNE` and `THOUSAND_TONNE` are different
units and must not be combined.

An unavailable value is stored as `NULL` with a non-empty `missing_reason`.
Missing observations never become numeric zero. A present value cannot have a
missing-value reason.

## Scope, classification, and provenance

Each record references an existing internal `Industry`; an optional
`SubIndustry` must belong to that industry. It references one `DataSource` and
retains one normalized `region_code`, source reference, revision number,
publication date/time, availability instant, and collection instant. Industry
and sub-industry IDs are the project's current canonical classification. Source
classification codes must be mapped to these IDs before the Application import
boundary. The model does not currently version classification schemes or keep
region codes in a separate master table. Region codes are opaque normalized
scope identifiers (for example `JP`, `GLOBAL`, or a project-defined market
region); consumers must match the full code and cannot infer geographic
containment.

The timestamps have separate meanings:

- `publication_date` is the source's published calendar date.
- `publication_datetime`, when known, is the source publication instant.
- `available_at` is when the observation became public/source-available and
  controls PIT visibility.
- `collected_at` is when the system retrieved the source record and never
  controls historical visibility.

Instants must be timezone-aware and are normalized to UTC. When a publication
instant is supplied, `available_at` cannot precede it. Publication dates are
not compared to a UTC date because the source timezone may differ.

## Point-in-time and revision policy

For a query at `as_of`, an observation is eligible only when:

1. `available_at <= as_of` after UTC normalization; and
2. its `observation_date` (point/event) or `period_end` (period) is no later than
   the UTC calendar date of `as_of`.

The query filters by these PIT conditions before selecting the greatest eligible
revision number for each source-scoped observation key. Deterministic ties use
`available_at` and then the persisted ID. Revisions from another source never
replace the selected source's revision. If the caller omits `source_id` and
eligible results contain multiple sources, the Application query rejects the
ambiguous request; it never merges or picks a provider implicitly.

The natural observation key contains industry, optional sub-industry, source,
signal type, temporal shape/date or period, and region. A revision number is
unique within that key. Rows are append-only through the repository contract;
corrections use a new revision, and the repository does not commit.

## Persistence and transaction behavior

Migration `0020_industry_signal_observations` creates the observation table,
RESTRICT foreign keys, shape/unit/value checks, PIT indexes, and unique partial
revision indexes for point/event and period records with and without a
sub-industry. Its downgrade removes only this table and its indexes. Import
validates industry, sub-industry ownership, source, units, dates, and duplicate
revisions before inserting. The caller owns commit and rollback.

## Classification and region master integration (Sprint 16)

Existing `industry_id`, `sub_industry_id`, and `region_code` remain unchanged.
Newly imported mapped observations may include both
`classification_version_id` and `classification_mapping_id`; the importer
checks the mapping target and validity on the observation's effective date.
Those references preserve the exact external crosswalk row. The migration does
not backfill old observations or infer region ancestors from existing codes.
Region master edges do not alter signal scope or cause aggregation. Historical
visibility remains governed by `available_at <= as_of`; classification
effective dates do not replace availability timestamps or use `collected_at`.
See [CLASSIFICATION_MASTER_SPEC.md](CLASSIFICATION_MASTER_SPEC.md) and
[REGION_MASTER_SPEC.md](REGION_MASTER_SPEC.md).

## Limitations

- No source adapters or live providers are included; these DTOs and use cases
  form the provider-neutral boundary for future adapters.
- No industry-signal aggregation or compatibility engine is included. Consumers
  must require matching signal type, region, industry/sub-industry, unit,
  currency, and period before comparing observations.
- Live classification or region data providers, automatic crosswalks, company
  assignment, and signal aggregation are not included. Mappings and graph edges
  are curated.
- A source may publish revisions with changed units or currency; this layer
  preserves the values and metadata without conversion. Consumers must not
  compare incompatible revisions as one series.
- Event dates represent when the announcement, addition, or completion was
  observed, not an independently modeled planned/actual future effective date.
- Revision selection is per provider. No consensus or cross-provider precedence
  policy is defined.
