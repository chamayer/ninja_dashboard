# PLAN-056 — Critical Software recovery, 2026-11-17

## Confirmed incident and authorization

User urgently requested restoration of the Software summary. Deployed .25's
protected application reader reports stale/publication_failed with no data.
Latest overview attempts fail because preparation inputs are not ready. The
sole unready owner is computer-client-ownership-sweep: its 15:24:29 run stalled
with worker_interrupted at 15:27:20 during the earlier .24 rollout. No live dirty
ownership/classification targets; all other declared input owners are ready.
Last retained publication was 15:22:16 and its window expired at 15:31:04 UTC.
No existing summary was certified fresh or exposed through a fallback.

## Immediate recovery

Reviewed and executed plan056_recover_ownership_input.py under emergency scope:
exact sole-failed-owner and interrupted-run guards, existing Jobs request API,
no direct data correction or claim bypass. Admitted sweep
26bda21a-3938-446b-b26b-2da8f76c5d45, observed running. No cancellations,
priority manipulation, scheduler lease, service restart or forced rebuild.

plan056_watch_software_recovery.py observes that run and the protected state,
with bounded read-only transactions and 15-second intervals. It may admit at
most one existing Software overview Job only after all inputs are ready and no
publication is queued/running. Final verification must use the actual Operations
reader role, not the ingest connection. No tests or repeated HTTP timings.

## Root cause and prevention candidate

Ownership dirty/sweep handlers were absent from REPLAY_SAFE_RECOVERY_EVIDENCE.
Their definitions therefore default to manual_review and interrupted work is
not admitted by the existing replay-safe recovery path. Software nevertheless
requires a completed owner watermark and correctly refuses the failed input.

Source review: ingest.main delegates to ownership.reconcile_dirty/reconcile_cycle;
these read local candidates in bounded pages, project each Computer atomically
and drain dirty revisions. No external source mutation is invoked. Existing Jobs
replay is idempotently linked to a stalled prior run, uses registered reviewed
policy, skips newer queued/running/completed coverage, and retries at most once
before requiring administrator review on another interruption.

Local candidate adds those two reviewed entries to shared/jobs_registry.py and
authority migration 0420, following existing recovery registration. Same handler
versions, claims, successor workflow, tenant guards and Software input fences;
no relaxed freshness, no direct publish and no new service/store/role.
Docker's existing shared/apps copies include both files. Authority evidence is
retained on rollback following the existing migrations' pattern.

## Permanent admission correction

User requested the permanent correction across publication entry points, then
approved commit/push including 0420/0421. Migration 0421 adds one tenant-guarded
Software readiness predicate based on the existing declared owner checkpoints,
dirty ownership/classification demand and active input work. Missing/unknown
metadata fails closed. Its fixed-search-path definer boundary and explicit
EXECUTE grants expose only readiness to the existing worker/app roles.

The existing expiry scheduler now requests publication only when that predicate
passes. More importantly, the central v6 Jobs claim selector gates every queued
software-overview candidate with the same predicate before acquiring execution
resources. v7 delegates non-source work to v6, so automatic, workflow and manual
publication requests share this gate. Unready requests stay queued; they do not
become fake successful runs and do not consume a publisher slot. Polling naturally
reconsiders them when inputs recover. No new retry loop or store is introduced.
Other Job eligibility/capacity/cancellation/scope/claim predicates are unchanged.

Begin/publish input fences still recheck after claim; concurrent input changes
remain protected. Last completed generation, live decision/security checks and
stale/expiry behavior remain unchanged. Existing Jobs input statuses expose the
failed dependency; no new notification channel is introduced. Audited input
replay remains bounded to the existing once-only recovery rules; persistent or
repeated-interruption failures remain visible for administrator intervention.

0421 depends on 0420; rollback restores the prior claim functions before dropping
the readiness helper. The scheduler tolerates an absent helper during rollout by
its existing UndefinedFunction handling. All Software input owner keys now have
reviewed recovery evidence; unrelated Jobs are not blanket-approved for replay.
No tests or failure-injection campaign. Source review alone does not certify all
failure/load scenarios or sustained freshness. Release 0.144.26 is approved.

## Checkpoint

Immediate recovery completed. Sweep succeeded; all input owners became ready and
the governed overview completed. Actual Operations-role read at approximately
17:17 UTC: current/completed, has_data=true. One normal authenticated Software
HTML verification at 17:17:04 UTC: HTTP 200, completed-summary marker, 47,292 bytes
in 0.820 seconds, normal logout confirmed. This is one populated internal-admin
observation, not sustained freshness/cold-path certification. No tests.

No current recovery process or scheduler lease remains. The permanent candidate
is source-reviewed only; user now approves commit/push including 0420/0421 and
automatic deployment. Prepare .26, push origin then mirror, observe rollout and
read actual protected Software availability. No tests or timing pass.
Temporary diagnostic/recovery files were removed from host/container staging.
