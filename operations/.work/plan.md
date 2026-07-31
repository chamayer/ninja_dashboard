# Active Operations implementation plan

Track: **Resolver correctness — shared-serial finding subject UUID**

**Status:** IMPLEMENTATION AUTHORIZED — repair the verified, pre-existing
resolver `DatatypeMismatch`, validate the complete resolver path, commit, push,
deploy, and measure the live outcome. Track B identity migration/cutover and
all unrelated work remain out of scope.

## Goal

Make the shared-serial data-quality finding use a UUID Device subject without
changing matching, merge behavior, finding semantics, lifecycle policy, or
source-observation identity.

## Scope

- Correct the shared-serial query in `ingest/identity/resolver.py`.
- Add focused disposable-PostgreSQL coverage proving UUID insertion,
  idempotent refresh, and retained JSON evidence shape.
- Deploy through the approved GitOps path and run one controlled resolver pass
  with aggregate-only verification.

Out of scope: identity matching rules, duplicate-device remediation, source
observation identity, schema migrations, Agent Compliance, and Track B.

## Decision

The primary finding subject remains the lexicographically first Device UUID,
selected deterministically from a UUID array. The JSON evidence continues to
contain text device IDs for compatibility. Shared serials remain a finding;
they never merge Devices automatically.

## Affected files

- `ingest/identity/resolver.py`.
- New focused PostgreSQL test under `ingest/tests/`.
- Root `VERSION` and `CHANGELOG.md` for the approved maintenance release.
- This plan and root coordination checkpoint.

## Steps

1. **Complete:** reverified the pre-existing production `DatatypeMismatch` in
   resolver line 1242, its code origin, architecture constraints, current
   plans, dirty worktree, and both remotes at `94cfb2c`.
2. **Complete:** corrected the UUID aggregation and added focused coverage.
3. **Complete:** local lint, focused PostgreSQL integration, resolver-adjacent
   tests, Python compilation, and diff check pass; the pre-existing
   full-file formatter churn is documented and excluded.
4. **In progress:** aggregate pre-deployment resolver/error/finding state is
   captured; commit, push `origin` then `a-m-rose`, and verify the automatic
   redeploy.
5. **Pending:** run exactly one controlled resolver pass, verify no resolver
   error, and report only aggregate outcome measurements.

## Validation plan

- Unit/static coverage plus a disposable PostgreSQL test that inserts a
  two-device shared-serial group and proves `findings.subject_id` remains UUID.
- Targeted ingest checks, Python compilation, Ruff, formatting, and diff check.
- After deployment: container/version/endpoint health, no HTTP 500 signature,
  resolver logs/run aggregates, and aggregate shared-serial finding counts.

## Checkpoint

Track A is complete at release `0.98.7` / commit `94cfb2c`; both remotes and
the deployed stack match it. The resolver defect was introduced in `863c1e31`:
the shared-serial subquery casts `d.id` to text before supplying
`findings.subject_id`, which is UUID. The exception is caught around the full
attribute-sync transaction, so that transaction rolls back while later ingest
pipelines continue. No customer data was inspected or retained. Existing dirty
root/Operations plans, backlog/design work, probes, and untracked ADR drafts
remain preserved. The user authorized this repair through commit, push,
automatic redeploy, and outcome measurement. The focused integration test
passes against disposable PostgreSQL: it verifies a UUID `subject_id`, retained
text `device_ids`, and idempotent refresh. Ruff lint and Python compilation
pass. The repository's pre-existing resolver formatting is not Ruff-format-
clean; applying its formatter would create unrelated full-file churn, so that
formatter result is recorded as a limitation rather than included in this
repair. Aggregate production baseline: version `0.98.7`, all relevant
containers/health endpoints healthy, 7 caught attribute-sync
`DatatypeMismatch` occurrences, no service 500 signatures, 1 shared-serial
group spanning 2 Devices, and 0 corresponding findings.

## Next action

Stage and review only the resolver repair files, then commit and push the
approved `0.98.8` maintenance release.
