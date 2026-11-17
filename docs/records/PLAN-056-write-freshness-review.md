# PLAN-056 — Write scope, freshness and refresh review

## Scope and evidence

2026-11-10: local source review after the user deferred cold-navigation timing
to post-fix verification. No production access, processing, new tests or runtime
changes. Existing uncommitted runtime edits are preserved. Findings describe
the checkout; they do not certify current deployed definitions or measured cost.

Reviewed current writers, their direct consumers, applicable SQL/Django
migrations and refresh callers. This completes this bounded consumer review,
not task 6's live job, lock or write-cost attribution.

## Relationship resolution: broad history update

`ingest/relationships.py:267` resolves current evidence only where source or
target entity IDs differ. It records that update count as `resolved`.
However, whenever `resolved` is nonzero, the next UPDATE at line 340 copies
endpoint, resolution and authority fields into **every open history row joined
to current evidence visible in the transaction**. It has neither a changed-ID
restriction nor an equality guard. There is no explicit active predicate in
that history UPDATE; do not describe it as updating active evidence only.

Thus one changed relationship can cause a population-wide history update.
This does not advance observation freshness: the six assigned columns are
source/target IDs, resolution status and three authority fields. This is a
more concrete candidate than indiscriminately suppressing heartbeat writes.
Its actual row count, duration and contribution to historical counters remain
unmeasured. The earlier +4,997 history updates are consistent with this shape,
but cannot be attributed to this function from global counters alone.

Candidate review must compare two semantics: restrict synchronization to
current rows changed by this invocation, or retain population-wide repair but
write only rows whose six copied fields differ. The latter retains the current
ability to repair an already stale open-history row outside the changed set.
Do not silently remove that behavior. Review history invariants, trigger effects
and source/tenant security before proposing implementation. Any new tests or
runtime edits retain their approval gates.

`upsert_current_evidence` separately updates `last_observed_at` on repeated
observations and creates history only on material change. The installed-source
definition of `queue_relationship_evidence` in migration 0111 compares material
and authority fields, excluding observation timestamps; heartbeat updates alone
do not establish repeated projector demand. Migration 0395 guards relationship
row upserts by input/status/selection changes, but replaces support rows for
selected projection tuples. These paths must not be combined into one claim
that every relationship write is redundant.

## Requirement verdicts: preserve evaluation freshness and scope

Migration 0332's `write_device_requirement_state` deletes/reinserts the selected
Computer scope, assigning `evaluated_at=now()`. The evaluator first locks and
checks captured client/evidence revisions; only eligible Computers are passed
to that writer (`ingest/evaluator.py:_write_requirement_state`).

`coverage_reads.home_summary` reports MAX(evaluated_at), and Coverage's page
and template display the evaluation time. A content equality guard alone would
make a successful unchanged evaluation appear old. A candidate must preserve
last-successful evaluation information, deleted/out-of-scope verdict cleanup,
ownership revision checks and same-transaction finding reconciliation. Storage
separation is an option for review, not an adopted schema change.

## Software readiness: freshness controls actionable exposure

`software_readiness.refresh` computes all tenant device/type rows and updates
all conflicts, including `assessed_at`. `software_reconcile._run` invokes it
even when a title subset is supplied; title-scoped reconciliation is therefore
not evidence of device-scoped readiness work.

The dependency is behavioral, beyond displaying a timestamp: SQL migration 114
defines `condition_fresh_until` from the earlier of readiness.assessed_at and
the aggregate assessment time plus the policy freshness interval. The exposure
view excludes rows after that deadline. Stopping timestamp updates on unchanged
readiness can remove actionable exposure. Any reduction must preserve successful
assessment freshness, policy version, offline transitions and exposure publication.
The direct reconcile queries consume readiness decisions but not its timestamp;
checking those Python callers alone would miss the SQL freshness contract.

## CVE matches: replacement and publication are separate decisions

Continuation qualification: the [shared-work map](PLAN-056-shared-work-map.md)
traces actual Jobs dispatch. Empty title scopes exit without readiness work;
nonempty incremental classification refreshes exposure, while whole-fleet
classification also refreshes safety. The older main entry point refreshes
safety after classification. Do not apply that older path to all scheduled runs.
The subsequent [amplification review](PLAN-056-background-amplification.md)
also distinguishes an empty title list from absent pending targets: absent
targets select the whole fleet, rather than the early-exit branch.

`intel/matcher.py:_match_and_upsert` snapshots the old content, deletes tenant
matches, reinserts the computed set and only then compares the six material
fields. Changed content controls history and reclassification targets, but
unchanged runs still replace the match rows. Inserts also recreate IDs and
default `matched_at`; the repository search found no production reader of that
timestamp by name. This limited finding does not prove external consumers absent.

A staged keyed difference is a candidate: retain unchanged matches and write
only added, removed or changed matches, preserving the unique match key,
empty-input deletion, version scope, atomic publication, history and target
generation. Equivalence and actual savings remain unvalidated.

Do not infer that unchanged match membership permits skipping software-safety
publication. The materialized view also reads mutable CVE scores/KEV metadata,
software title totals, safety signals, aliases, decisions and time-relative
three-year predicates. The matcher refreshes it after matching; classification
also refreshes it and the exposure read model. A membership-only refresh gate
would miss other inputs and time passage. Duplicate refresh cost is unmeasured.

## Activities: no-insert refreshes can still change results

`activities/ingest.py` invokes all three summary refreshes after a successful
collection, even when `inserted` is zero. Two rollups in SQL migration 068 use
a moving 180-day window. Their membership can change as time passes without
new events. A zero-insert shortcut therefore needs an expiry/publication policy,
not merely an insert-count guard. Retention and payload deletion remain undecided.

## Result and next action

The narrowest newly identified write candidate is relationship-history
synchronization: avoid rewriting equal history fields while preserving its
existing repair scope. CVE difference writes are a separate, larger candidate.
Readiness and requirement freshness cannot be optimized by dropping timestamp
updates without preserving their consumers. No remedy is adopted or implemented.

Next: compare these candidates with confirmed read remedies in the platform
recovery proposal, separating measured failures, code-proven amplification and
unmeasured benefits. Coverage remains the first confirmed high-priority fix
candidate. Per-job cost, waits, refresh duration and live definitions remain
explicit measurement gaps; no repeat idle baseline or cold timing is needed
to draft that proposal.
