# PLAN-015 — One-time source-record identity reconciliation

## Status and goal

Active. Defined and started 2026-10-21. The implemented preview is read-only;
this document authorizes no runtime or production-data change.

For each existing source record, answer: **If this record arrived unattached
today, would the current resolver attach it to another Computer?** Produce a
read-only fleet preview, then separately review and approve the exact repairs.
Use the existing hostname-and-client fallback as well as stronger identifiers;
do not require a serial merely because this is a reconciliation.

## Problem and confirmed limits

The normal polling resolver selects unattached observations. Its matching
ladder includes existing source identity, serial, VM UUID, hostname plus MAC,
and hostname, according to enabled database policies. Existing attachments can
therefore preserve a historical split after the matching logic improves.
The matching helper has a `skip_source_identity` option, but source review
found no caller activating that recheck. Verify this against deployed code
before implementation; local code alone does not establish deployed behavior.

The investigation found source records for one reported machine on separate
Computers. This can make a Computer appear to lack Ninja, LogMeIn, or another
required platform even though a peer Computer holds that platform. Hudu
documentation can also remain unattached when its Ninja integration cards
resolve to different Computers. Unresolvable cards alone do not cause Hudu
divergence: the existing Hudu resolver already ignores those when another
card resolves. Multiple distinct resolved Computers cause divergence.

The earlier fleet counts are preliminary, not an accepted repair footprint.
The SentinelOne query used an incorrect platform name, and the shared-identifier
aggregation did not prove that both Computers supplied the identifier.
Correct and rerun the measurements. Do not infer that SentinelOne is unaffected
or that any counted pair is safe to merge. A same-name peer is a discovery
signal, not proof that the current attachment is wrong.

## Scope and ownership

- Scan every current record in configured identity-signal streams, including
  already attached records, across the authorized tenant/client scope.
  Discover streams and source names from registries; cover Ninja, LogMeIn,
  SentinelOne, and other enabled identity sources without a vendor allowlist.
- Include records attached to active, aging, pending-cleanup, or retired
  Computers in the preview; preserve normal matching and retirement rules.
  Inventory inactive/withdrawn records separately as retained evidence, not
  incoming current records to be moved automatically.
- Reuse the deployed matcher, normalization, policy priorities, rejection and
  roaming rules, candidate ranking, and explicit operator exclusions.
- Assess resulting Hudu links and missing/stale platform verdicts. Hudu cards
  remain pointers to source records, not independent permission to merge.
- PLAN-004 owns ongoing identifier-change rechecks. This plan owns the one-time
  reconciliation and must coordinate edits to shared identity code with it.
  PLAN-012 owns page populations/readers; PLAN-014 owns requirement applicability.

Out of scope: changing matching policy, cross-client reassignment, recurring
automatic reconciliation, source-side cleanup, blanket same-name merges,
deleting empty Computers, changing requirement policy, or bypassing the shared
projectors. Any necessary policy/schema change must be proposed and reviewed
before implementation proceeds beyond this scope.

## Counterfactual matching contract

1. Pin the deployed code revision, enabled policies, normalization rules,
   source snapshot generations, operator decisions, and evidence boundary.
   Evaluate on a consistent read-only snapshot with isolated matcher caches.
2. Identify the record by its complete stable source identity, including tenant,
   source instance, namespaces, and parent identity. Treat sibling observations
   describing that same record as one unit; distinguish agent/VM records and
   namespaces even when their numeric IDs coincide.
3. Suppress that record's existing attachment shortcut and its own evidence in
   candidate names, identifiers, activity/ranking, history, and cached data.
   `skip_source_identity=True` alone is insufficient unless all these paths
   are verified. Keep its current Computer eligible on independent evidence;
   do not simply exclude that Computer from the candidate set.
4. Apply the normal incoming-record logic using the record's current client,
   reported name, usable identifiers, online state, and configured policies.
   Preview must never promote a new Computer or invoke a mutation indirectly.
5. Preserve hard conflicts and operator separation. Explain conflicts using
   serial/VM UUID evidence and applicable simultaneous same-source activity.
   Verify source timestamps and entity types; collection time alone does not
   prove simultaneous activity. Respect roaming and placeholder exclusions.
6. Record the selected destination and every relevant candidate, matching rule,
   tier/rank, compared evidence, exclusion, and policy version. Outcomes are
   unchanged, proposed reattachment, review required, or no existing match.
   A result that would normally promote becomes a reported outcome only.

Hostname plus client remains a valid fallback. Multiple candidates must show
the normal winner and the reason, including activity/age tie-breaking. Flag
those cases for explicit review rather than silently treating the tie-break
as proof. Report disagreements between accepted ADR-0032, deployed policies,
and implemented guards before selecting which rule would govern application.

## Preview and repair contract

Preview records stay in an approved private location outside Git; repository
documentation receives aggregate counts and validation only. Capture old and
proposed Computer IDs, stable source-record identity, decision evidence,
blockers, dependent operations, and a deterministic digest of the proposed set.
Do not print credentials or unrestricted payloads.

Evaluate proposals together, not just independently. Detect cycles, reciprocal
moves, competing destinations, and newly combined conflicting records. Specify
a deterministic operation order and expected final memberships. Cases whose
destination depends on another proposed move require review or a new preview;
the tool must not chase changes to convergence during an approved application.

Distinguish two operations:

- **Reattach a record** when that record belongs elsewhere but its old Computer
  may still represent a different machine. Move its related observation
  memberships consistently and retain the old Computer and history.
- **Merge Computers** only when whole-Computer evidence justifies it. Use the
  existing audited merge operation and its existing protections. A record-level
  match does not automatically authorize moving all findings, software,
  decisions, or other records from the old Computer.

Audit the existing validated attachment and merge writers before choosing an
apply path. Every approved move needs the old/new membership, matching rule,
evidence, reason, action identity, and closed/open link history. Capture an
exact reversal manifest and verify recovery without rewriting historical
source evidence. Do not implement application as a bulk `device_id` update.

Application defaults to disabled and requires explicit approval for the
reviewed count/digest and operation types. Before each atomic operation,
revalidate memberships, evidence, policies, decisions, and destination scope;
abort on drift rather than silently changing the approved plan. Serialize
against relevant collector/resolver mutations using existing supported locks.
Verify a repeated apply is an audited no-op, and retain partial-completion
state if multiple transactions are necessary.

After approved identity changes, use the established workflow to synchronize
source links, re-resolve Hudu pointers against the new memberships, and refresh
claims/effective projections, names, presence, lifecycle, findings, and stored
requirement verdicts in the actual dependency order. Verify that Hudu's stored
relay resolutions are updated; refreshing presence alone is not sufficient.
Specify refresh cost, failure recovery, and approval coverage in the apply
proposal. An interrupted refresh must be visible and resumable.

## Steps and affected files

1. Reconcile PLAN-004 status, deployed revision, policy rows, ADR-0032, and the
   implemented matcher. Define the exact stable-record and self-exclusion rules.
2. Implement the read-only counterfactual adapter around the shared matcher,
   with no policy fork, new dependency, public-interface change, or schema
   change unless separately reviewed. Add a default-preview operator entrypoint.
3. Validate with synthetic PostgreSQL cases, then rerun the authorized fleet
   measurement across all configured platforms. Trace reported examples by
   stable source identity when names differ; absence of a name match does not
   close a reported case.
4. Review candidate moves, blockers, Computer merge eligibility, combined-set
   conflicts, refresh/recovery steps, and the pinned preview. Present the exact
   repair scope for separate approval before any production writes.
5. Implement/validate the approved apply path, obtain any required release and
   deployment approvals, apply only the reviewed set, and verify the resulting
   memberships and dashboard outcomes. Record actual validation and known
   commit hashes before marking the plan complete.

Expected implementation review areas: `ingest/identity/matching.py`,
`ingest/identity/resolver.py`, a scoped operator entrypoint under `ingest/`,
`ingest/device_map.py`, `ingest/connectors/hudu.py`, `ingest/derived.py`, existing
Operations attachment/merge writers, focused identity/Hudu tests, and runtime
Dockerfile packaging. These are candidate areas, not approved edits.

On activation, place the detailed checkpoint in `operations/BLUEPRINT.md`, add
a concise root `BLUEPRINT.md` pointer, and update PLAN-004/PLAN-015 registry
dependencies before editing overlapping runtime files. Preserve existing
unrelated work. Document any durable decision beyond accepted identity rules
in an appropriately numbered decision record before completion.

## Validation and acceptance

- Preview executes under a read-only transaction and leaves all database
  state, queues, source APIs, operator decisions, and maintenance claims intact.
- Synthetic cases prove unchanged attachments, hostname/client fallback without
  serials, late identifiers, re-enrollment, duplicate observations, returning
  retired records, conflicting hardware, simultaneous agents, VM namespaces,
  roaming records, explicit separation, ambiguous ranking, and tenant isolation.
- The record cannot select its old Computer using its own sibling/history
  evidence or stale cache; independent evidence can still select that Computer.
- Group-level tests cover reciprocal moves, conflicts introduced by combined
  proposals, drift rejection, idempotence, atomic failures, and recovery.
- Separate reattachment and merge tests verify history and dependent-row
  ownership; no unrelated findings/software/decisions follow a record move.
- Hudu regression proves cards converge after corrected source identities while
  genuine divergent cards remain conflicted. Missing/stale verdicts agree with
  evaluator output after refresh across Ninja, LogMeIn, and SentinelOne.
- Report aggregate outcomes per source/lifecycle, identity groups, blockers,
  Hudu effects, and predicted/actual coverage changes; do not sum overlapping
  groups as distinct Computers. Distinguish missing imports from misattachments.
- Run targeted project tests, relevant Python/Django/Ruff checks, packaging
  review, `python scripts/validate_plan_registry.py`, and `git diff --check`.
  Record unavailable checks explicitly. Production verification is separate
  from local validation; no version bump is needed for this proposal.

## Current checkpoint and next action

The read-only preview implementation is complete locally. It uses the shared matcher
with source identity skipped and excludes the reviewed observation from candidate
names, identifiers, conflicts, and activity ranking. Current observations are
evaluated; inactive observations are listed as retained evidence rather than
proposed moves. The output is a new private JSON file outside the repository,
and the command has no apply option. Focused PostgreSQL matcher coverage passed
(15 tests), as did Python compilation, Ruff, plan-registry validation, and the
repository whitespace check.

An authorized production read-only hostname/client footprint query completed on
2026-10-21. It found 131 attached active records with exactly one peer and 40
with multiple peers, before serial/VM, roaming, operator-exclusion, and
simultaneous-agent guards. The guard-aware follow-up reduced the one-peer set
to 110 and retained 40 multi-peer review cases. Neither made a change; both
are discovery evidence only.

All 40 multi-peer records were confirmed covered by an open
`duplicate_device_records` or `identity_conflict` Finding; multiple records can
belong to one Finding group.

Next action: review the 110 guard-aware candidates. Application, merges, and
derived-data refresh remain separate gates.
