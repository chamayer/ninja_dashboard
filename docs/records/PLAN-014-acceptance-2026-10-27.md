# PLAN-014 — Acceptance continuation

Status: active; local candidate validated. Release `0af8aac` is the baseline;
the user approved preparing reported-state fallback after the diagnosis below.
No production write, recalculation, migration,
deployment, commit or push was performed in this continuation.

## Current production diagnosis

Read-only checks on 2026-10-27 at 23:52 UTC used tenant 1, repeatable-read
transactions, bounded statement/lock timeouts, and the documented shared SSH
helper. The runtime-role query saw 6,114 Computers, confirming tenant visibility.
An initial probe used the wrong tenant setting and returned no rows; it was
discarded. The corrected probes use `operations.tenant_id`. No zero-drift claim
is based on the discarded query. Restricted observation details were read
through the deployed ingest runtime's own connection, never by disabling RLS.
Only aggregate results were returned; no subject identifiers or payloads were
retained. A runtime-role permission denial and a NOLOGIN-role connection attempt
made no changes and were replaced by that ingest-runtime read-only path.

Current disagreement function: 114 findings across 109 distinct
Computer/entity/platform/disagreement entries. Recorded open drift also has 109
entries. All are `finding_without_verdict`; missing/stale-without-finding is zero.
Counts changed through normal scheduled processing since the earlier 141-entry
checkpoint; this task did not request evaluation.

The deployed summary reports 51 entries retained by current guards and 58
requiring review. Direct inspection and the shared lifecycle calculation split
the latter group:

| Entries | Confirmed cause | Disposition |
| --- | --- | --- |
| 13 | Qualified contact-aging cleanup; current live `device_offline` cover; fresh reconciliation assessment permits clearing, but cleanup deliberately retains history. Twelve have no verdict and one has an exempt verdict. | Diagnostic explanation gap; preserve episodes. |
| 45 | Twenty active Computers lack qualified lifecycle evidence: 12 have ScreenConnect remote-access records and eight have R-U-ON monitoring records. Contact timestamps are null, while explicit online/offline values are present. Some also have Hudu documentation, which has evidence mode `none`. | Genuine uncertainty under the registered `direct_contact` policy; do not clear or classify as accepted retention. |

The 45 entries include 28 with absent verdicts and 17 with missing verdicts.
They have current blocked reconciliation assessments and no cleanup root.
ADR-0011 and ADR-0047 permit explicit reported state only under its registered
mode. A collection timestamp is not contact. Changing that policy requires a
reviewed decision; the continuation does not silently enable reported state.
After an explanation of the safety tradeoff, the user chose to prepare the
reported-state fallback change. That authorizes the candidate below, not
production migration or recalculation.

## Scoped diagnostic correction

`ingest/requirement_state.py:summarize_state` now recognizes the 13 cleanup
entries only when the exact tenant/Computer has a current reconciliation
assessment under the active policy, is non-deleted cleanup without explicit
confirmed use, and its live cover names an active `device_offline` episode for
the same Computer. The parent must have qualified contact-policy duration and
be detected at least as recently as the assessment. Unknown lifecycle,
old/missing parents and confirmation do not qualify. Raw disagreements,
history, verdicts and findings remain unchanged.

Executing the candidate summary against production inside a read-only process,
without installing or deploying it, returned 64 retained and 45 requiring
review. This is diagnostic evidence, not zero-unexplained-drift acceptance.

## Reported-state fallback candidate and impact

The new registered mode `direct_contact_state_fallback` opts in
`agent.remote_access` and `agent.monitoring`. Recognized explicit state is
eligible only when the Computer has no qualified direct contact from any
source. Existing four modes, including hybrid VM-host behavior, are unchanged.
Unknown/null state and equal-time conflicts remain uncertain. Fallback
negative reports carry unknown duration: no contact time, contact-aging
cleanup or extended-offline root is inferred. Existing offline roots remain
until positive recovery. Requirement guards distinguish current reported
offline state with `offline:reported_without_duration`.

Pending migration 0357 extends the existing mode constraint and Django choices
and updates only the two reviewed type rows under an explicit change action.
It refuses missing/unexpected starting registrations; reverse SQL restores
contact-only registration and the previous constraint. It neither rewrites
history nor automatically reverses later lifecycle transitions. No additional
persisted authority or runtime dependency was introduced. Existing Dockerfile
directory copies include all changes; Compose, ports and entrypoints are
unchanged. VERSION/CHANGELOG still describe baseline 0.129.3; release preparation
and production execution require separate approval.

A second read-only preview ran the candidate lifecycle functions in a temporary
ingest process with prospective registry values substituted in fetched rows,
within a repeatable-read, read-only database transaction. No registry values or
runtime files were installed. It found these changes:

| Platform | Newly qualified online | Newly qualified offline, duration unknown |
| --- | ---: | ---: |
| ScreenConnect | 5 | 38 |
| R-U-ON | 57 | 2 |
| Total | 62 | 40 |

All 45 unexplained entries gain qualified evidence: 30 are associated with
online state and 15 with offline state of unknown duration. This is an evidence
preview, not a prediction that all 45 findings close. Normal evaluation must
recompute verdicts and assessments; offline and other current guards retain
their authority. Direct-contact Computers were unchanged by the preview.

Current covered requirements total 2,098: 807 missing and 1,291 stale.
Parent-type counts are 1,904 under offline, 86 under missing-source cleanup and
134 under unknown OS; some children have multiple parents, so these counts are
not additive. Zero covered children lack an active, same-tenant/same-subject
parent. Actionable unknown-OS findings total 100, within the original approximate
91–183 estimate. The old 2,232 covered total (875 missing, 1,357 stale) is a
historical fleet snapshot, not a fixed target for current source processing.

## Reviewed rollout and recovery boundaries

Review the scoped diff, then obtain commit approval separately from production
push. Release preparation must update VERSION and CHANGELOG together. The push
approval must name migration 0357 and the automatic Portainer deployment;
push origin before the required mirror, without a separate redeploy. Confirm
the migration and both relevant application runtimes before functional
acceptance. An old ingest runtime does not recognize the new mode and can
temporarily block contactless evaluation during a mixed-version interval;
that interval cannot establish acceptance. Wait for normal evaluation or obtain
explicit authorization to trigger it. Rollback and manual migration retain
their own approval boundary; restoring contact-only policy does not undo audit
history or lifecycle changes already made by normal evaluation.

Root `AGENTS.md` says the origin push automatically deploys and forbids an
extra redeploy; `docs/operations.md` still describes an immediate manual
trigger. The explicit repository instruction governs the proposed rollout;
this continuation invoked neither. Unrelated ScreenConnect grouping and
coverage-card edits appeared in the shared worktree during validation and were
preserved outside this candidate. Shared registry/checkpoint files require
scoped staging when a commit is approved.

## Validation checkpoint

- Final focused ingest batch: **135 passed**. It includes the lifecycle,
  requirement-state/reconciliation, safety, scope, runtime-role, migration,
  live-cover, snapshot/serialization and new fallback tests.
- Operations: **43 passed** (26 coverage-label tests and 17 PostgreSQL migration
  tests for 0304/0332/0333). Django system check and `makemigrations --check
  --dry-run` pass with no model-state changes missing.
- PostgreSQL integration cases used disposable PostgreSQL 16 and synthetic
  data, never production copies. The final ingest batch used `PGOPTIONS=-c
  jit=off` to avoid expensive compilation of tiny fixture queries. Earlier
  summary tests also passed with default JIT settings.
- The first broader run had 109 passes and four failures: a concurrency fixture
  omitted its synthetic password; two old lifecycle assertions contradicted
  the accepted no-contact behavior or used a null projected power state beside
  an explicit power observation; and a source-string safety assertion still
  forbade the accepted investigating-root recovery. Fixtures were corrected,
  and actual investigating-root recovery is now exercised with live cover.
  Early new-summary fixture failures were also corrected before the final run.
- Focused Ruff, new-file formatting, syntax and whitespace checks pass.
  Registry validation passes. Root `BLUEPRINT.md` remains over its existing
  4,000-byte governance limit (6,794 bytes at the final check); full governance
  is therefore not claimed. The ingest checkpoint is below 4,000 bytes.
- Packaging was inspected. Full-stack startup/browser behavior, stress tests,
  a representative synthetic full-fleet performance benchmark and production
  candidate acceptance remain unverified. The read-only full-fleet lifecycle
  preview is functional impact evidence, not a performance benchmark.

Production completion still requires approved deployment and current
zero-unexplained-drift evidence after evaluation. A diagnostic reclassification alone cannot
complete PLAN-014. The original covered-finding/impact baseline remains in the
[build record](PLAN-014-build-2026-10-27.md); changing fleet counts are not fixed
acceptance targets.
