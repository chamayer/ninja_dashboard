# PLAN-037 — Source collection failures

**Status: active.** Registered 2026-11-01 from the post-release check of
0.140.0. Each remaining step needs the user's approval.

## Goal

Every open "source failure" Issue reflects a source that is failing now, and
each one either gets fixed, is retired with its source, or clears by itself
once collection succeeds.

## Open source-failure Issues (read-only, 2026-11-01 21:10 UTC)

| # | Source | Open since | Recorded error | Evidence |
| --- | --- | --- | --- | --- |
| 1 | NinjaOne (`…0011`) | 11-01 21:02 | Jobs worker shutdown interrupted the handler | The 0.140.0 redeploy interrupted the running collection. Last 7 days: 138 completed, 23 failed, 20 stalled by worker shutdowns. A user-approved re-run was queued 21:11. |
| 2 | abuse.ch ThreatFox (`5c3964c5…`) | 10-21 | `410 Gone` for `threatfox.abuse.ch/export/json/recent/` | 28 failed runs in 7 days, none completed. The export URL appears retired. |
| 3 | AlienVault OTX (`f64ce7b2…`) | 10-26 | The read operation timed out | Latest run 11-01 18:02 completed; 1 failure in 7 days, yet the Issue stays open. |
| 4 | Hudu (`ba4744de…`) | 10-27 | Execution exceeded the safety deadline | Latest run 11-01 17:55 completed; the Issue stays open. |
| 5 | AMROSE ScreenConnect (`dcaecb81…`) | 10-29 | Jobs worker shutdown interrupted the handler | Latest run 11-01 19:32 completed; the Issue stays open. |
| 6 | LogMeIn (`…0014`) | 10-30 | 1 source collection(s) failed | Latest run 11-01 17:44 completed; the Issue stays open. |
| 7 | agent_compliance (domain) | 10-07 | Exceeded 180 min, presumed hung | The agent-compliance source is retired; nothing will ever clear this Issue. |
| 8 | LogMeIn (platform key `source_failure:LogMeIn`) | 09-17 | No successful run since 10-01 | Legacy platform-keyed episode from before binding-scoped failures; LogMeIn now also has binding Issue 6. |
| 9 | SentinelOne (platform key `source_failure:SentinelOne`) | 09-20 | No successful run since 10-01 | Legacy platform-keyed episode; check whether SentinelOne still collects under a binding. |

Issue 1 (Ninja) closed at 21:20 UTC: a user-approved evaluation ran after the
scheduled Ninja run completed at 21:18. Issues 3–6 have completed runs and did not
close in that evaluation, which is Step 1's question.

## Steps

| Step | Item | Notes |
| --- | --- | --- |
| 1 | Find why Issues 3–6 stay open after a completed run | Their latest collections completed, so the source-failure guard should have cleared them. Read how `_source_failure_guard` and the admin assessment decide `may_clear` (current-observation clear assessment, PLAN-036) and why these episodes are not closed. Read-only first. |
| 2 | Fix or retire the ThreatFox collection | Confirm abuse.ch's current ThreatFox export endpoint and authentication; update the collector, or disable the binding if the feed is no longer used. |
| 3 | Close the retired and legacy Issues | Close agent_compliance (retired) and the legacy platform-keyed LogMeIn and SentinelOne episodes with closure reasons, and stop raising source failures for retired domains. |
| 4 | Do not raise a failure for a run a deploy interrupted | 20 Ninja runs in 7 days were stalled by worker shutdowns, and each redeploy opens a source failure until the next success. Candidate: treat `worker_interrupted` as retryable and retry it once before raising. |
| 5 | Ninja failed required steps | 23 Ninja runs in 7 days failed a required step (`devices`). Read the retained diagnostics; this may overlap the Ninja collection-gap item in `TODO.md`. |

## Validation

Read-only production checks before and after each step; the Issue count by
source; host tests for any collector or guard change.

## Status (2026-11-02)

- Steps 1 and 3 are done. 0.140.1/0.140.2 record a recovered source's assessment
  so its Issue closes (Issues 3–9 closed); 0.140.3 (migration 0396) closes the four
  pre-binding per-step Ninja failures (`core.devices`, `core.device_health`,
  `core.custom_fields`, `patch_cycle`, last seen 09-16).
- Step 2 is done. 0.142.0 collects ThreatFox through the authenticated API; the
  first run on it (requested 17:36, completed 17:53 UTC on 2026-11-02) completed
  without error after every run since 10-21 had failed with `410 Gone`.
- Step 5: no failed `devices` steps since 2026-11-01 17:36 UTC; the failures stopped
  before 0.142.0, cause not confirmed. 0.142.0 now loads Ninja locations and
  policies before devices (the device table references both); the first run on it
  completed without error in 23.5 minutes (17:57–18:20 UTC).
- Step 4 is not started. Evidence today: the 0.142.1 deploy restarted the Jobs
  worker at 17:56 UTC and stalled the running SentinelOne and LogMeIn refreshes.

## Next action

User approval for Step 4 (deploy-interrupted runs).
