# Region Master

## Region identity and relationships

`Region` is an extensible coded node with one declared type: `GLOBAL`,
`CONTINENT`, `COUNTRY`, `ECONOMIC_REGION`, `MARKET_REGION`, or `UNSPECIFIED`.
`RegionRelationship` distinguishes two meanings:

- `CONTAINS` expresses geographic/hierarchical containment. For example, Asia
  contains Japan and Europe contains Germany. This is the only edge type used
  by ancestor/descendant hierarchy queries.
- `MEMBER_OF` expresses a country's membership in an economic or market region.
  For example, Germany and France are members of the Eurozone. It does not make
  the Eurozone a geographic child of Europe (or Asia), and it is not traversed
  by containment queries.

A country may be a member of multiple economic or market regions. The model
does not currently represent `PARTICIPATES_IN`: that would imply a separate
participation/organization concept not required by the present use cases.

Containment edges form an acyclic directed graph, not a single-parent tree.
The application validates endpoint existence, relationship-specific endpoint
types, duplicate edges, and containment cycles before insertion. Membership
edges are not hierarchy edges; they are currently constrained to connect a
country with an economic or market region and are not included in cycle
detection or hierarchy traversal. For schema compatibility the stored edge is
oriented with the group in `parent_region_id` and the member country in
`child_region_id`; semantically, that country is `MEMBER_OF` the group. Both
relationships are explicit and a region may have multiple parents where the
relationship semantics permit it.

Queries use stored edges only. Parent lists, descendants, and all ancestor paths
are deterministic and traverse `CONTAINS` only. Direct member/membership
queries use `MEMBER_OF`; region code prefixes are never interpreted as
relationships. Inactive nodes remain queryable for historical references. The
master does not aggregate a child region's observations or membership values.

## Industry Signal compatibility

Migration `0021_classification_and_region_masters` leaves historical
`region_code` values unchanged. It creates no regions or guessed relationships
from those values. Signal observations keep their existing scope and meaning;
the region graph is a separate reference layer for explicit future use.

Migration `0022_region_membership_relationships` broadens the existing
relationship type check to admit `MEMBER_OF`. It rebuilds the SQLite table via
Alembic batch mode, preserving relationship primary keys and existing
`CONTAINS` edges. Downgrade restores the old constraint only when no membership
rows exist; otherwise it stops without deleting data.

No geographic inference, region conversion, or aggregation is performed.
Country and economic-region semantics require curated inputs. Application
cycle and duplicate checks are transaction-scoped; concurrent graph writes
should be serialized by callers. SQLite does not provide a declarative
acyclicity constraint, so direct SQL writers can bypass graph validation.
