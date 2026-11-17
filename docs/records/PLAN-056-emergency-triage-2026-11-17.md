# PLAN-056 — Emergency recovery triage, 2026-11-17

## Scope and outcome

User redirected the resume to emergency recovery and requested that the agent
identify the failure. Bounded deployed checks on am-ch-01 at approximately
14:04–14:08 UTC identify slow interactive reads, not missing Software publication
or an unavailable service. No runtime application fix, restart, cancellation,
queue change, migration, release, commit or push was performed. Recovery remains
incomplete: the observed Home and Software pages miss their latency budgets.

## Observed evidence

- Operations, ingest, Jobs worker and Postgres report healthy.
- Protected Operations-role Software read: current/completed, data present.
- One authenticated internal Home HTML request: HTTP 200, 10.735 s, 36,397 bytes.
- One authenticated internal Software HTML request: HTTP 200, 2.185 s,
  48,047 bytes, completed-summary marker. Both normal logouts confirmed.
- Cache state for those HTTP requests is unknown; admin/internal HTML evidence
  excludes browser and external-network costs and does not certify other roles.
- Separate one-shot read-only Home handler trace: 7.233 s total, 7.031 s SQL,
  40 queries. Main execute costs: Software `home_summary` 2.3279 s;
  Source Records `home_summary` 1.7110 + 0.5985 s; Issues `home_data` 1.3806 s.
  This starts with an empty process-local cache and excludes middleware/network;
  it is attribution, not an exact decomposition of the separate HTTP request.
- Latest Software publication completed at 14:02:34.588 UTC, 46.69 s after start.
  The four latest publication runs completed; an earlier failed run reported
  changed preparation inputs. Ownership/classification pending=false, no active
  Software input owners, zero unconsumed reclassification targets, all input
  owners ready. No missing-publication recovery is indicated by this snapshot.
- Last 24 hours: 210 completed overview runs, mean 56.510 s, maximum 232.578 s;
  39 classification-only runs, mean 174.846 s, maximum 389.729 s. These are run
  durations, not end-to-end freshness measurements or full/reuse classifications.
- One resolver run is active with a fresh heartbeat; one platform-evaluate run
  was queued. Diagnostics report one contained claim; its cause/impact was not
  attributed. Historical failed/stalled totals do not establish a current outage.
- Activity snapshot shows one active resolver-related query and no lock blocker.
  Host has 32 CPUs, approximately 30 GB available RAM, root filesystem 5% used.
  Swap is almost full, but two current vmstat intervals show 65–74% idle CPU,
  zero I/O wait and negligible swap-in/no swap-out. This does not support an
  immediate resource-exhaustion intervention; longer-term pressure is unmeasured.

## Method and validation

Used the documented SSH helper for remote commands and reviewed Python files
copied to the target and invoked by path. Existing diagnostics:
`plan056_overview_read_state.py`, `plan056_current_jobs.py`,
`plan056_software_emergency_state.py`, `plan056_http_pilot.py`,
`plan056_platform_home_http.py`, and `plan056_software_http.py`.
The older emergency-state script also returns a fixed-date ownership update
count; that count is not evidence for this incident and was not used.

Added `scripts/diagnostics/plan056_emergency_home_trace.py` for one read-only
handler attribution with 12-second statement/one-second lock limits and a
35-second process deadline. It rejects shared cache configuration, emits code
locations/timings only, discards results, and confirms connection closure.
Reviewed source before copying; local compilation and deployed execution passed.
No test files or existing application working changes were modified.
Plan-registry validation (55 entries), Python compilation and whitespace checks
passed. All active handoffs remain under 4,000 characters. Temporary diagnostic
files were removed from host/container staging after execution; container root
was needed to remove the root-owned copies created by `docker cp`.

## Recovery decision and next action

Do not use a service restart, queue cancellation or manual rebuild to treat the
observed request-time fleet derivation. Prepare a scoped Home read-path remedy
at the domain owners, starting with Software (largest single measured query),
using compatible existing protected results where available. Preserve distinct
Home risk/action semantics: the published Software high-risk metric is not a
substitute for Home's active-risk-finding count. Existing uncommitted Home and
Software simplification candidates are excluded work, not an approved release.
Source Records and Issues costs also remain; fixing Software alone cannot
establish Home's latency target. No blanket cache or new schema/store/role design.

Any candidate must preserve unavailable/freshness behavior and receive focused
correctness and complete-request validation. Commit and deployment approvals
remain separate. No emergency production mutation is supported by this snapshot.
