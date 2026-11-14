# Historical Valuation Percentile Engine

## Scope

Sprint 11 calculates five separate historical valuation percentiles: PER, PBR,
EV/EBITDA, normalized PER, and normalized EV/EBITDA. It does not combine these
measures into a score, signal, screen, or backtest. A price percentile is not a
valuation multiple percentile and is not calculated by this engine.

## Percentile semantics

The method is the empirical cumulative distribution function (ECDF):

`percentile = 100 * count(historical_value <= current_value) / valid_count`.

Ties count as less than or equal to the current value. A value strictly below
the historical minimum ranks at 0%; equality with the minimum includes all
minimum ties. Equality with or a value above the maximum ranks at 100%. The
current daily observation is part of the distribution when its eligible
snapshot falls in the requested range. This is a rank, not min-max scaling.
Values are stored to seven decimal places.

## Observation frequency and selection

Daily trading observations are used where stored valuation snapshots exist; the
engine does not resample to monthly data. For each observation date and metric,
the latest eligible snapshot is selected deterministically by snapshot cutoff
and ID. A later same-date snapshot supersedes the earlier one and the superseded
row is retained in the audit with an exclusion reason. Multiple market sources
or different financial source sets are not merged. An explicitly selected
financial source must be the snapshot's complete source set: `(selected_id,)`.
A snapshot containing the selected source plus another source is excluded with
an audit reason; it is never treated as selected-source-only. Missing source
metadata is likewise excluded when a source is selected. Without an explicit
financial source, every observation must identify exactly one source and all
observations must use the same source; multi-source combinations and missing
metadata require an explicit deterministic policy, which Sprint 11 does not
provide, so the request is rejected. These rules apply to raw and normalized
valuation metrics. Rejected-source snapshots remain auditable but do not
supersede a valid snapshot for the selected source on the same date.
The recorded period bounds describe the earliest and latest source observations
considered, including rejected rows. The daily sampling choice can overweight
longer listing histories and periods with more available sessions; no correction
or resampling is silently applied.

## Lookback rules

`3Y`, `5Y`, and `10Y` windows use inclusive calendar-date bounds ending on the
UTC date of `as_of`; their start is the corresponding calendar anniversary,
clamped to February 28 when needed for leap-day anniversaries. If a listing
starts after the computed bound, its listing date is used. `AVAILABLE_HISTORY`
starts at the security's earliest recorded listing date. If no listing record is
available, the first stored observation is used. Coverage ends at `as_of`; no
later observation date enters the calculation.

## Point-in-time requirements

The query cutoff is timezone-aware and normalized to UTC. Valuation snapshots
must have an observation date no later than the query cutoff and their own
snapshot cutoff must be on that observation date. Each source reference must
have `available_at <= snapshot.as_of`; a referenced market observation cannot
post-date the valuation observation. `collected_at` is never used to decide
historical visibility.

For normalized multiples, the engine first looks for a Sprint 10 result with
the exact historical valuation cutoff and requested normalization configuration.
If one is absent, it assembles market and financial inputs for that historical
date through `BuildValuationInputs`, then invokes `CalculateNormalizedEarnings`
with that same cutoff and source policy. Sprint 10 therefore chooses only
financial revisions visible at the historical cutoff. Results and the
percentile snapshot participate in the caller's transaction; the engine does
not commit. Repeated calculations append new snapshots and do not rewrite old
results. If no base valuation snapshot exists for a date, that date does not
provide a normalized sample.

## Invalid observations and comparability

Only positive, finite multiples are valid. The Sprint 09 metric status carries
input validity: non-positive EPS or EBITDA, invalid book value per share, and
unavailable inputs produce a non-available snapshot which is excluded with its
status/reason. Missing data is never replaced with zero. Normalized valuation
statuses are handled the same way.

The current snapshot is compared only with observations sharing its currency,
unit, financial-period basis, and calculation version. Normalized valuation
period basis includes its normalization method and requested/effective window.
Incompatible observations are excluded with a reason. Same-date deduplication
selects the highest `(snapshot cutoff, snapshot ID)` among eligible snapshots;
each other eligible snapshot is recorded once as superseded. The selected
snapshot is recorded once as included or excluded, and the excluded count is
the number of excluded audit rows. Currency conversion, FY-versus-TTM conversion, and calculation
version conversion are not attempted. If current inputs are missing or invalid,
the result has no percentile and carries an explicit status and reason.

## Coverage, status, and confidence

Coverage is `valid distinct trading-session observations / expected trading
sessions` for the actual lookback interval. The denominator comes from the
configured local `TradingCalendar`, never calendar days. An unconfigured
calendar makes coverage unavailable and the result status `UNAVAILABLE`.
Missing trading sessions lower coverage but do not increment excluded
observation count; that count is for stored snapshots rejected by status,
validity, PIT, comparability, or deduplication.

The default configurable policy requires 20 valid observations for `AVAILABLE`.
Counts below the configured minimum yield `INSUFFICIENT_DATA`. Confidence is
`LOW_CONFIDENCE` at the minimum count, `MEDIUM_CONFIDENCE` from 60, and
`HIGH_CONFIDENCE` from 120, with the latter tiers requiring at least 80% session
coverage. Count thresholds and the coverage threshold are configurable through
`PercentilePolicy`. Confidence is a sample/coverage indicator, not a claim about
source reliability. `data_quality` separately reports whether snapshots were
excluded.

## Persistence and limitations

Migration `0015_valuation_percentiles` adds append-only percentile result and
input-audit tables. Results record the requested lookback, actual observation
bounds, current value, percentile, historical minimum/maximum/median, valid and
excluded counts, expected sessions, coverage, confidence, status, comparability
metadata, version, and input snapshot links. Exclusion reasons are retained.
Repositories do not expose mutation or deletion operations; caller-owned
transactions control commit and rollback.

Coverage depends on the configured weekday/holiday calendar, which is not a
complete exchange calendar feed. Daily observations give longer histories more
weight. Available history is limited by existing daily valuation snapshots;
normalized series can only be reconstructed for dates with an eligible base
valuation snapshot. Corporate-action adjustments, currency conversion, live
providers, and source reliability scoring are not implemented. No
Value/Cycle/Opportunity score, screen, signal, or backtest is included.
