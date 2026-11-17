# PLAN-056 — Software preparation writes

2026-11-13, continuing the user-authorized emergency freshness correction.
92cc6e70 / 0.144.21 is deployed. Its real reuse run e4344d42 completed in
14.95 seconds. Full preparation still took 71–80 seconds. Logs show readiness
preparation about 20 seconds and assessment/exposure work about 40 seconds.
Every full pass proposes 83,239 readiness rows and unconditionally updates them,
plus unchanged assessments and participant insertion attempts.

The existing producers still recompute every desired fact. Persistence filters
out rows whose complete stable payload matches a still-valid stored row and
participants whose full key already exists. Meaningful changes, new records,
policy changes and deletions retain their existing path. Retained facts keep
their original assessed_at, which is conservative. Unchanged facts renew at half
the existing policy freshness_hours window, before the unchanged expiry limit.
There is no increased validity allowance or fake reset of old source freshness.
Security/claim/tenant guards remain; no new storage or migration.

Scope: software_readiness.py and software_reconcile.py, root release files.
No test edits or broad suite. Validate syntax/SQL shape and one actual full
preparation through Jobs, then protected Software state and full authenticated
HTML. Do not claim the 60-second bound until an actual full run meets it.

eab79e1d / 0.144.22 deployed to both remotes. Actual full-preparation run 9faaa858
started 18:19:15.134 and completed 18:20:15.615 UTC: 60.48 seconds. The generation
published at 18:20:14.344, but public availability waits for Jobs completion, so
the 60-second target was still missed. Protected reader current/completed;
populated HTTP 200, 47,917 bytes in 2.123 seconds, normal logout confirmed.

Subsequent automatic full-preparation run 764b623a started 18:21:46.794 and
completed 18:22:34.727 UTC: 47.93 seconds including Jobs completion. Logs confirm
preparation reused=False, 83,239 readiness rows evaluated, and exposure publication.
Generation e5f892a5 published at 18:22:33.927. Thus the actual full path met the
60-second target in this observation, without relying on the 14.95-second reuse
path. The latest protected read is current/completed; all services healthy.
Temporary scheduler lease release was confirmed.

A further local readiness memoization candidate passed five existing computation
checks in 0.21 seconds but was withdrawn before commit/push once the normal full
run met the target. VERSION/CHANGELOG and readiness source were restored to
deployed 0.144.22; no 0.144.23 was released. No test files changed or broad suite.

The five-minute delivery deadline was missed. These observations do not certify
every load/rebuild case or sustained end-to-end freshness. Full policy rewrites,
queue delays and genuinely expired inputs can still require more work. Page
latency remains open at 2.123 seconds. No further tuning or test campaign is
authorized by this record alone; the broader PLAN-056 worklist remains active.

## Local resume review — 2026-11-17

HEAD `eab79e1d` and VERSION 0.144.22 corroborate the local release checkpoint.
No production state was inferred from them. Reviewed the Software overview
entry point against root ADR-0006; this is source attribution, not certification
or a new performance campaign. Existing staged/unstaged runtime and test changes
were preserved. No runtime/test file was edited or external command executed.

| Baseline | Current mechanism and remaining limit |
| --- | --- |
| R1 | `software_overview.read_overview` checks active authenticated tenant/permission and rejects client context before calling the protected SQL reader. Prior superuser-writer limitation remains unresolved; source review is not restricted-role proof. |
| R2 | Overview publication remains domain-owned; Products and CSV still use `_software_page_data`. Cross-surface population/decision parity remains an acceptance gate. |
| R3 | Published HTML adds `_software_recent_installations` (LIMIT 10) and requested-key labels. These bound returned rows/keys, not proven database execution cost; no representative plan was run. |
| R4 | `preferred_software_display_names` deduplicates normalized keys and resolves them in one query. Shared request/middleware cost remains part of full-page acceptance. |
| R5 | `software_page` HTML calls `_software_published_overview_data`; protected-read failure returns unavailable without live aggregate fallback. Legacy live helpers still serve other paths. |
| R6 | `ingest.inventory.software.refresh_overview_read_model` uses one transaction, begin/publish claim and input fences, and guarded preparation reuse. `operator_job_queue._admit_expired_software_overview` owns expiry admission; sustained maintenance is unverified by this resume. |
| R7 | The protected reader/context distinguish current, pending, stale and unavailable, including missing/failed inputs. Migrations 0416/0417 separate automatic delivery from material invalidation. No current live availability claim is made. |
| R8 | Existing <=1.5 s ordinary / <2 s cold HTML budget remains. Recorded 2.123 s misses the hard maximum; recorded 47.93 s full preparation does not prove the complete committed-change-to-visible-result freshness bound under sustained load. |
| R9 | Overview CSV still passes `_software_page_data` titles to `csv_response`; it is separate from compact HTML. Export completeness/bounded execution remains unverified; no export change is authorized here. |

Reviewed next diagnostic: `scripts/diagnostics/plan056_overview_read_state.py`.
It initializes the existing Operations runtime, opens a read-only tenant-scoped
transaction with a 10-second statement timeout, calls the protected reader and
prints only state, reason and data-presence. It does not enqueue work, mutate
data or produce HTTP/timing acceptance. External execution awaits authorization
under the repository's external-validation boundary. The root and Operations
handoffs now route to this check instead of the obsolete missing-first-result
assertion. Registry validation (55 entries) and `git diff --check` passed.

The subsequent user redirection to emergency recovery authorized bounded live
diagnosis. See [2026-11-17 triage](PLAN-056-emergency-triage-2026-11-17.md) for
current availability, HTTP and Home attribution; the source-review-only limits
above describe the preceding step, not the later incident checks.
