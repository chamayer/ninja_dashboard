# Active Operations implementation plan

Track: **Corrective Track B — stable identity marker cutover**

**Status:** COMPLETE — stable identity cutover and run-start hotfix deployed and verified

Both remotes and production resolve to hotfix `30c460c` / release `0.100.1`;
migration `0096` is applied. The rejected permanent per-run membership table
was not implemented.

The current cross-service Ninja snapshot expansion is tracked exclusively in
the root `.work/plan.md`; this completed Operations plan remains the record for
the stable-identity cutover.

## Goal

Cut observation identity and complete-snapshot reconciliation over to the
ADR-0009 stable source tuple without retaining one membership row per identity
per poll. Keep one current raw record per stable source identity and append
history only for material or presence transitions.

## Scope

- Revise ADR-0009 from permanent run membership to current-row run markers.
- Re-key current/open-history identity, locks, upserts, history, snapshot runs,
  reconciliation, resolver, compatibility seeds, and dependent consumers to
  the stable tuple.
- Make complete-run reconciliation safe for overlapping runs using
  `last_snapshot_run_id`, `last_received_at`, and the run-start boundary.
- Keep compact run-level count/digest evidence and durable withdrawal-run
  provenance; do not store raw per-run membership.
- Preserve legacy columns and constraints through comparison and rollback.
- Validate locally and present the reviewed migration/deployment gate before
  any production-affecting push.

Out of scope: permanent per-run membership, exact historical membership
replay, legacy-column removal, historical deletion, Agent Compliance, Ninja
snapshot cleanup, ADR-0010 ecosystem implementation, and unrelated admin work.

## Affected files and surfaces

- `operations/docs/decisions/0009-stable-source-observation-identity.md`
- `operations/apps/core/models.py` and the next reviewed Django migration
- `ingest/observations.py` and `ingest/observation_runs.py`
- Source collection transaction boundaries and snapshot scopes
- Observation seed/backfill commands, resolver/read paths, and focused tests
- RLS/grants, retention, Docker packaging, `VERSION`, and `CHANGELOG.md`
- `ingest.Dockerfile`, `operations.Dockerfile`, `README.md`, and the explicit
  `docker-compose.workstation-ca.yml` local overlay for an optional BuildKit CA
  secret used only when workstation HTTPS inspection requires it

## Decisions

- There is exactly one current raw row per stable source identity and endpoint
  namespace. Each accepted observation updates its timestamps, raw payload and
  hashes, transport provenance, and `last_snapshot_run_id` in place.
- No permanent membership table is created. The prior 30/90/365 sizing remains
  evidence for rejecting that write amplification, not a table specification.
- A run summary may retain an observed-identity count and deterministic digest.
  The digest is audit/comparison evidence only and never reconciliation
  authority.
- Only a successful, explicitly complete snapshot may withdraw evidence.
  Partial, failed, and abandoned runs withdraw nothing.
- The database application transaction serializes per tenant, source instance,
  and snapshot scope from `begin_run` through reconciliation; remote API fetch
  work may still overlap. Reconciliation may withdraw only an active row not
  marked by the deciding run whose `last_received_at` predates that run's
  start. This makes newer evidence visible before any older absence decision.
- Withdrawal marks source evidence inactive; it never deletes the current row
  or canonical entity. It closes the open history interval with deciding-run
  provenance. Reappearance reactivates the same current identity and opens a
  new interval.
- Legacy identity remains available for rollback until stable-key comparison
  and a rollback rehearsal pass. Contract cleanup is separate.

## Steps

1. **Complete:** deploy and verify expand/backfill `0.99.0` / `edc1e16`.
2. **Complete:** deploy dual-write `0.99.1` / `5760cd6` and identify the
   pre-existing per-heartbeat advisory-lock scaling defect.
3. **Complete:** deploy lock repair `0.99.2` / `fe1beda`; verify all five
   source families, zero stable collisions/mismatches, zero HTTP 500s, and no
   shared-lock exhaustion.
4. **Complete:** size the proposed permanent membership table and reject it
   after design review because it would add about 228,987 retained rows/day
   for a requirement that current-row run markers already satisfy.
5. **Complete:** revise ADR-0009 and inspect every stable-key,
   reconciliation, history-provenance, run-summary, RLS, and consumer surface.
6. **Complete:** implement the smallest coherent local migration and code
   cutover while retaining legacy rollback columns/constraints.
7. **Complete:** run focused unit/PostgreSQL, full ingest/Operations, Django,
   migration-state, Ruff, syntax, packaging, and diff validation; review every
   changed hunk and check local HTTP behavior where the stack permits.
8. **Complete:** repair the local Docker validation path without weakening
   TLS. Pass the workstation-trusted inspection root as an optional BuildKit
   secret, remove it in the same dependency-install layer, document the local
   command, and rebuild both application images. Ordinary and production
   builds must remain independent of the local certificate.
9. **Complete:** present the exact migration and automatic Portainer deployment
   effects for explicit commit/push approval. After an approved origin push,
   verify migrations, health/readiness, aggregate comparison, and HTTP 500s
   before updating the mirror.
10. **Complete:** repair the post-deployment raw-SQL/default mismatch.
    `begin_run()` must explicitly insert `observed_identity_count = 0`; the
    PostgreSQL regression fixture must omit its artificial database default so
    future tests match Django's deployed schema.

## Validation plan

- Test stable identity across collector replacement and reclassification.
- Test new-row locking, current upsert, open-history uniqueness, material
  change, withdrawal, restoration, and deciding-run provenance.
- Test that partial/failed runs withdraw nothing and that an older overlapping
  run cannot withdraw evidence received at or after its start boundary.
- Test run count/digest determinism without persisting member rows.
- Confirm RLS/grants and migration forward/backward ordering.
- Run the relevant full suites, `manage.py check`, migration checks, Ruff,
  Python compilation, Docker packaging/build where the workstation trust chain
  permits it, and `git diff --check`.
- External checks, if separately deployment-approved, use only the documented
  helper and return aggregate counts or service metadata—never payloads,
  external IDs, hostnames, clients, or customer records.

## Checkpoint

Both `origin/master` and `a-m-rose/master` resolve to `fe1beda`; Portainer is
deployed at that commit. Ingest, Operations, and Postgres were healthy after
the lock repair. The all-source verification recorded 23,732 current writes,
279 material-history writes, five complete runs, zero missing shadow fields,
zero binding/instance/run mismatches, zero active-current or open-history
stable collisions, zero Operations HTTP 500s, and zero ingest lock/OOM events.
No customer data was returned.

The current code already has the bounded storage primitive:
`entity_observation_current.last_snapshot_run_id` is updated in place on each
accepted observation, and reconciliation operates in the same source
transaction. The pending cutover must change reconciliation from binding scope
to stable source-instance scope and add the run-boundary guard before that
marker becomes authoritative.

The previously recommended permanent membership table was not implemented.
Measured projections—approximately 6.9M rows/30 days, 20.6M/90 days, and
83.6M/365 days—demonstrate why it is the wrong default. The accepted correction
keeps compact run summaries and run-linked transition history instead.

Unrelated dirty root plans, docs, backlogs, local probes, and the ADR-0010
draft remain preserved.

Release `0.100.0` now re-keys current/open-history locks, lookups, upserts, and
constraints to the stable tuple. One transaction advisory lock per tenant,
source instance, and snapshot scope is acquired in `begin_run` and retained
through reconciliation, so same-scope database application cannot expose an
uncommitted overlap race. A complete run withdraws only active evidence not
marked by that run whose last receipt predates the run start. Withdrawal closes
the active history interval without rewriting its historical `active` value
and stores the deciding run; restoration reopens history on the same current
identity. Run records retain only a distinct identity count and deterministic
digest.

Migration `0096` fails closed on incomplete identities, current/open-history/
run stable collisions, missing run starts, and current/history presence
mismatch. Aggregate-only production preflight returned zero for all seven
categories and zero runs missing source identity or start boundary. No
customer data was returned. The migration adds no table and requires no new
RLS policy or table grant; existing table RLS/grants continue to cover its
columns.

Validation completed:

- Full ingest and Operations suite: 85 passed, one expected container-only
  skip.
- Disposable PostgreSQL 16: initial write, material history, empty complete
  withdrawal, run-linked history close, restoration, collector replacement,
  reclassification, stable uniqueness, and competing scope-lock behavior all
  passed.
- Actual Django `0096` forward migration and reverse were exercised against a
  disposable PostgreSQL 16 fixture. Forward constraints/columns/non-null state
  and run-count backfill were verified; reverse removed them and restored the
  nullable pre-cutover state. The fixture faked prior migrations and therefore
  lacked Django content-type tables, so its post-migrate permission signal
  could not complete; the `0096` transaction itself committed and was
  inspected in both directions. The disposable container was removed.
- `manage.py check`, `makemigrations --check --dry-run`, Python compilation,
  focused Ruff/import checks, formatter checks for replaced/new files, and
  `git diff --check` passed.
- Before the trust-path repair, both Dockerfiles included the changed runtime
  directories but image builds stopped during dependency download because the
  workstation Docker/PyPI path could not validate the issuer certificate;
  neither reached application packaging.
- Follow-up diagnosis confirmed that the workstation's Geder Filter HTTPS
  inspection root is trusted by Windows but absent from Linux image trust. The
  proxy presents only a re-signed leaf to the build. The approved repair is an
  optional, local BuildKit CA secret; disabling verification or committing the
  workstation certificate is prohibited.
- A public-only copy of that root was exported to the user-local path
  `%USERPROFILE%\.docker\ninja-dashboard\workstation-ca.crt`. Both application
  images built successfully with it: ingest image
  `sha256:2a2d81c3c53...` and Operations image `sha256:256ece5e03aa...`.
  Finished-image checks proved the local root file and trust were absent;
  packaged ingest imports and the containerized Django system check passed.
- The explicit local Compose overlay validated and built both services using a
  temporary environment-backed secret. Cached ordinary builds also completed
  without supplying the secret, confirming the mount is optional. Compose's
  pre-existing warning that the root `version` attribute is obsolete remains
  unrelated to this repair.
- Commit `fc1d482` was pushed to both approved remotes. Portainer deployed
  release `0.100.0`; migration `0096` completed successfully after an active
  preflight scan, and Operations, ingest, and Postgres became healthy.
- Startup collections raced the migration and initially failed on the
  not-yet-present cutover columns/constraints. Post-migration reruns of
  LogMeIn, ScreenConnect, and SentinelOne then exposed a separate raw-SQL
  contract defect: all three run inserts violated the non-null
  `observed_identity_count` column. Django's migration-time default is not a
  persistent database default, while the disposable PostgreSQL fixture had
  incorrectly declared `DEFAULT 0` and masked the defect. No source run
  committed observations from those failed attempts.
- Release `0.100.1` now explicitly inserts zero for the run's initial observed
  identity count and removes the artificial fixture default. Ten focused unit
  tests, both disposable PostgreSQL integration tests under the production
  no-default schema, focused Ruff/compilation, `git diff --check`, and the
  secure ingest image build passed. The hotfix adds no migration and changes no
  identity, reconciliation, or retention semantics.
- Hotfix `30c460c` was pushed to `origin` and `a-m-rose` as one approved
  combined operation. Portainer deployed ingest `0.100.1`; migration `0096`
  remained applied. Ingest, Operations, and Postgres are healthy, readiness and
  health endpoints pass, and the Operations root returns its expected redirect.
- Post-hotfix startup collections completed for LogMeIn (3,048), ScreenConnect
  (1,006), and SentinelOne (4,250): three complete runs, zero failed, 8,304
  writes, 8,304 distinct observed identities, no missing digest, and no
  count/write mismatch. Aggregate database verification returned zero
  incomplete current/history/run identities, zero stable current/open-history/
  run-boundary collision groups, and zero current/open-history presence
  mismatches. All 25 post-hotfix history closures have deciding-run provenance.
  Post-hotfix logs contain zero ingest error lines, zero Operations error lines,
  and zero Operations HTTP 500s. No customer-level data was returned.
- The user established a durable push policy: one explicit approval may cover
  both remotes as a combined operation. Push `origin` first and the mirror
  immediately afterward; perform deployment validation after both pushes.
## Next action

Corrective Track B is complete. Return to the root ecosystem plan for the next
approved slice. Legacy observation-key cleanup, rollback-column removal,
historical snapshot cleanup, and Agent Compliance remain outside this track
and require their documented later gates.
