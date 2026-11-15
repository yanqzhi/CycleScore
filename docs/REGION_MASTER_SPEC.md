# Region Master

## Region identity and relationships

`Region` is an extensible coded node with one declared type: `GLOBAL`,
`CONTINENT`, `COUNTRY`, `ECONOMIC_REGION`, `MARKET_REGION`, or `UNSPECIFIED`.
Containment is stored separately as directed `RegionRelationship` edges. This
forms a directed acyclic graph, not a single-parent tree: economic and market
regions can legitimately overlap across countries or continents. The
application validates endpoint existence, type compatibility, duplicate edges,
and cycles before insertion. A region may have multiple parents.

Queries use stored edges only. Parent lists, descendants, and all ancestor paths
are deterministic; region code prefixes are never interpreted as ancestry.
Inactive nodes remain queryable for historical references. The master does not
aggregate a child region's observations into a parent.

## Industry Signal compatibility

Migration `0021_classification_and_region_masters` leaves historical
`region_code` values unchanged. It creates no regions or guessed relationships
from those values. Signal observations keep their existing scope and meaning;
the region graph is a separate reference layer for explicit future use.

No geographic inference, region conversion, or aggregation is performed.
Country and economic-region semantics require curated inputs. Application
cycle and duplicate checks are transaction-scoped; concurrent graph writes
should be serialized by callers. SQLite does not provide a declarative
acyclicity constraint, so direct SQL writers can bypass graph validation.
