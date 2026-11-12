# PLAN-056 — Software readiness recovery, 2026-11-12

## Confirmed cause and approved correction

Five rows in computer_client_ownership remain dirty for deleted Computers.
The ownership reconciler intentionally selects only nondeleted Computers, but
software_overview_inputs counted every dirty row. This was an impossible
publication prerequisite, independently of active lock contention.

The user explicitly approved applying the prepared one-function correction
(`do it`, after the concrete approval question). Applied at approximately
14:44 ET through the reviewed plan056_software_guard_fix.py --apply, using the
approved remote helper. The script verified exactly one expected guard in the
live function before replacing it. Statement/lock deadlines were 8/2 seconds.

The guard now joins the same-tenant Computer and requires deleted_at IS NULL.
No ownership/table data was changed, and checks on live Computers remain.
CREATE OR REPLACE retained the function's owner, grants, security-definer and
search-path properties. The transaction committed successfully. Live ownership
readiness changed from true to false; repeated subsequent reads confirmed it.

Local migration 0414 preserves this correction. The scheduler's equivalent
predicate is corrected locally, not deployed. Existing local Sources migration
0413 now depends on 0414 to avoid a local migration branch; its staged copy
predates that dependency edit. Do not commit unrelated staged candidates.
No VERSION/CHANGELOG change, commit, push or deployment was made for this
manual correction. A release still needs the existing separate approvals.

## Operational recovery and remaining failure

The user explicitly authorized stopping every interfering Job. Governed
cancellation was requested for competing work; identified blocking DB queries
were cancelled. A cancelled Source Record assessment child that continued
holding resources was terminated only after checking its exact process/run
against the recorded cancellation. The supervisor retained responsibility for
terminal state and claim release; no Job completion was fabricated.

Bounded recovery windows used the existing scheduler-leader session lock to
prevent new scheduled admissions, automatically releasing it at exit. Existing
queued competitors were cancelled through Jobs. No permanent schedule or
capacity configuration was changed. One earlier release was confirmed; the
latest window must also be confirmed released before reporting cleanup.

Software classification completed and pending targets reached zero; ownership
and classification gates are clear. At approximately 14:48 ET the only reported
unready owner was Platform evaluation, run b45e48a4, still running after about
nine minutes and issuing ownership queries. The overview attempted publication
but correctly refused that incomplete input. No overview publication existed.
Software's empty page is therefore NOT fixed or accepted. Do not bypass input
gates or claim the complete Software contract is implemented.

No additional test suite ran. Syntax compilation and the live before/after
readiness checks passed. Full Software HTTP validation cannot establish success
until a completed publication exists. Temporary reviewed state/recovery/fix
scripts remain in host/ingest/worker /tmp and need cleanup after recovery.

Next: let the governed Platform evaluation finish under the recovery window,
then confirm its completion-triggered overview publishes and check one complete
Software page. If it fails, report its actual cause rather than certifying data.

## Terminal-result correction

Subsequent direct lookup confirmed b45e48a4 completed successfully. The readiness
function selects a different, newer-requested run cc895735: stalled with
prerequisite_failed and started_at NULL. It never executed and did not publish
an input. This explains why successful evaluation did not clear readiness.

Prepared 0415 and plan056_software_checkpoint_fix.py to exclude never-started
attempts from owner checkpoints, retaining actual started-run failures and
legacy completed history. This is an additional manual function correction;
Explicit approval was subsequently granted for this correction and everything
needed in the scoped emergency session. Applied around 14:56 ET; all owner
checks became ready after the in-flight ownership Job completed. Ownership and
classification pending gates are false, and an overview Job is running in a
temporary recovery window. No Job completion was fabricated. Local syntax
compilation passed; no suite ran.

## Persistence candidate — 0.144.15

The user's latest emergency approval covers the necessary scoped corrections,
commit, both pushes, automatic deployment and reviewed 0414/0415 persistence.
No repeat approval is requested. Release contains only the scheduler's matching
nondeleted-Computer predicate, those two migrations, VERSION/CHANGELOG and this
record. The unrelated Sources 0413, inventory view changes, navigation, Home,
tests and global contract documentation remain outside this release.

0414 depends on deployed 0412; 0415 depends on 0414. The unshipped local Sources
0413 depends on 0415 and is not required by this release. Operations copies the
entire apps directory; ingest copies its runtime source. No packaging change
or new ingest migration is needed. Forward/reverse CREATE OR REPLACE retains
existing function owner/grants/security boundaries; no table data is changed.
These function corrections are already approved/applied live; startup migrations
make them reproducible. No standalone redeploy is permitted after the push.

First certified publication succeeded around 14:58 ET. A configured-admin full
Software HTML request returned 200 in 1.371 s, logout confirmed, but lacked the
completed-summary marker. Runtime-role protected read returned pending/input_changed
with no data, so this is NOT full-page acceptance. The running old scheduler still
requests ownership work for deleted rows; release includes its matching fix.
After automatic rollout, request one governed refresh and recheck read/HTTP state.

## Release 0.144.15 and reader recovery

Committed cf3945ed, pushed origin then a-m-rose; both verified at
cf3945ed3158ae89799c805badcd56076591a616. Automatic deployment completed;
ingest VERSION 0.144.15 and dispatcher SHA-256
b307c8a81b8546bb8764a9794ceac8750798a991955e7a5a224ac70338bc8804 match.
All three application services were healthy; 0414/0415 were marked applied.
No standalone redeploy. Prior unrelated staged candidates remain excluded.

All owner watermarks matched the publication, with no pending classification
or ownership demand. The reader nevertheless withheld data while an automatic
overview refresh ran. This was its unconditional active-refresh invalidation,
not an actual input change. The user asked why the old summary was withheld.
Under the existing emergency authorization, corrected the reader so an automatic
refresh alone does not invalidate a still-valid completed generation. Explicit
operator requests and every real input/security/expiry/failure guard remain.
Migration 0416 preserves this exact correction; no stored data or Job status edits.

Live runtime-role read became current/completed with data. One authenticated
full HTTP request at 20:05 UTC returned 200, 47,556 bytes, Completed summary,
in 2.577 seconds; logout confirmed. The visible empty-page failure is repaired.
This misses the <=1.5 s ordinary / <2 s hard target, so performance/contract
acceptance is still OPEN. Earlier 1.37 s pending pages were not successful
populated-page measurements. No additional test suite or test-file edits.

0.144.16 contains only 0416, VERSION/CHANGELOG and this evidence. The ongoing
emergency approval covers its commit, both pushes, automatic deployment and
reviewed migration. Existing local Sources 0413 now depends on 0416 but stays
excluded. Syntax/whitespace and packaging/migration-order review passed.
