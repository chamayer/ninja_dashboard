# PLAN-002 verification — 2026-10-26

## Conclusion

PLAN-002 is complete. The binding-scoped source-refresh architecture is
deployed, and the worker replay correction is present in the deployed 0.129.1
line. After the Oct 26 Ninja source refresh and its single recovery retry were
interrupted during worker shutdowns, a subsequent Ninja refresh completed and
published output after the worker remained healthy. A separate ThreatFox
endpoint failure is a connector defect and does not belong to PLAN-002's
completion gate.

## Code and release evidence

- The archived PLAN-002 checkpoint records binding-scoped schedules, fenced
  successful output publication, the shared source-refresh handler, and
  Sources/Jobs ownership. It also records migration 0269 rollout and health
  checks.
- Commit `8a33233` added `replay_interrupted_runs()` and worker startup/heartbeat
  calls. The function retries only reviewed replay-safe work, once, preserving
  scope and payload and linking the retry. It deliberately does not replay a
  recovery run that is interrupted again.
- `8a33233` is an ancestor of the 0.129.0 release. Production reported ingest
  version 0.129.1 and the Jobs worker healthy during this review.
- PLAN-019 owns newer acquisition/publication correctness items; they are not
  folded into PLAN-002 completion.

## Read-only production snapshot

Checked 2026-10-26 at approximately 21:47 UTC, tenant-scoped through the
Operations application connection:

- 16 enabled source bindings; all 16 have schedules.
- 469 successful source-refresh outputs in seven days, covering all 16
  bindings. No enabled binding lacked an output in that period.
- Seven-day source-refresh runs: 465 completed, 19 failed, 26 stalled, 2
  queued, and 2 running. Two bindings' latest terminal run was failed or
  stalled, but no latest successful output had exceeded its freshness window.
- One source-refresh recovery retry was interrupted (`worker_interrupted`) at
  20:50 UTC. A later hourly run was running at 21:47 UTC; the latest output for
  that binding was from 19:57 UTC. No output from the follow-up had been
  published yet.
- The Jobs worker container was healthy. Django showed no unapplied
  migrations.

## Follow-up check

At 21:56 UTC, the automatic replay of the Oct 26 worker-interrupted Ninja
source refresh was itself stalled with `worker_interrupted`; neither the
original run nor its replay had published output. This remains the specific
PLAN-002 resume gate. The enabled `reference.abusech` binding has stale output
(last published October 21) because its ThreatFox request to the retired legacy
export URL failed with HTTP 410 on October 26. This is an upstream endpoint
issue, unrelated to Jobs recovery; the current ThreatFox API requires an
Auth-Key, and production has `ABUSECH_AUTH_KEY` configured. It is tracked
separately from PLAN-002.

The stored error for both Ninja runs is `Jobs worker shutdown interrupted the
handler; verify external and database effects before retrying.` This confirms
the Jobs worker shut down while each child was running. The worker container
currently running started at 21:12 UTC and was healthy; Docker's retained event
query returned no matching historical task events. The shutdowns are consistent
with the intervening redeploys, but the run ledger does not record the initiating
event, so their exact trigger is not proven. The remaining check is one
successful Ninja source refresh after the worker remains up without another
shutdown.

At the same check, other source-refresh runs were actively executing or queued.
These are a point-in-time observation and do not themselves establish a Jobs
contract defect.

The source catalog and scheduled runs remain monitored operationally, but
connector-specific endpoint health is not a PLAN-002 closure criterion. No
production data was changed.

## Completion verification

Read-only production query at 22:08 UTC found a Ninja source refresh requested
at 21:36, started at 21:43, and completed at 22:07 UTC. It has one
`source_refresh_outputs` row. The Jobs worker container started at 21:12 UTC,
was healthy at verification, and had zero restarts. This completes the
remaining PLAN-002 resume gate.

## Next action

No further PLAN-002 action. Track the ThreatFox endpoint repair independently.
