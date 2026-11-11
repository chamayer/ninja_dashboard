# PLAN-056 — Release 0.144.11

## Approved release scope — 2026-11-11

The user explicitly requested commit and push of the four reviewed recovery
slices. Origin is the deployment authority; the same release must then reach
the secondary mirror. The push includes automatic Portainer deployment.
No separate redeploy, migration invocation or data operation is included.

The release starts from `ca00938a`, verified as both remotes' master tip before
preparation. Four separate logical commits contain only:

| Commit | Scope |
| --- | --- |
| `76bca1c1` | Correlated Coverage lifecycle lookup and synthetic PostgreSQL tests |
| `30489aa5` | Null-safe relationship-history equality guard and focused tests |
| `3d8d7dfc` | CVE matcher difference publication, focused tests and ADR-0057 |
| `b3229b73` | Home Issues compact projection/grouping and focused parity tests |

The release-metadata commit updates VERSION and CHANGELOG together. It includes
this record but does not add unrelated working files, diagnostic scripts,
unreleased Home caches, middleware changes, Software summary/card changes or
legacy planning edits. Those remain preserved in the original working tree.

## Migration and instruction review

A bounded production read-only ledger check ran through the workspace SSH helper
using `operations_app`: three-second statement and one-second lock limits,
transaction READ ONLY and ROLLBACK. It compared all checked-in baseline migration
names against the deployed ledgers: 410 Django and 119 ingest entries, **zero
pending baseline migrations**. In particular, Django 0406 and ingest SQL 119 are
already applied. The four release slices add/change no migration file.
Two preceding attempts failed before querying (shell quoting, then an unset
container variable); no migration or data change ran.

VERSION/CHANGELOG had remained at 0.144.10 despite the later already-deployed
Home/patch-outcome baseline commits. Release 0.144.11 reconciles that metadata
without adding those changes again.

`docs/operations.md` still describes manually invoking redeployment after push;
root AGENTS.md explicitly requires automatic deployment and prohibits a separate
redeploy. Follow AGENTS.md. No private Portainer action is invoked.

## Validation of the isolated release tree

A temporary detached worktree was assembled from the baseline with only the
approved paths. Its views.py contains only the Coverage join hunk; original
working-tree cache and Software hunks were excluded. Validation in that isolated
tree passed:

- 63 focused correctness/SQL tests across all four slices.
- One existing Home request/template composition test.
- Four matcher target-generation concurrency cases; six unrelated cases excluded.
- Django system check; targeted Python compilation and lint, allowing only the
  two HEAD-confirmed Issues selector complexity findings.
- Registry, whitespace, packaging and release metadata checks.

PostgreSQL checks used sequential disposable containers with small synthetic
fixtures; no local fleet processing or timing comparison. Existing unrelated
Coverage regression failures are retained in the local implementation handoff;
this release does not claim the whole repository suite passes. Governance hooks
also flag the existing old status date in docs/current-state.md.

## Push and acceptance boundary

Push the release tip to origin/master, then a-m-rose/master without an intervening
validation gate. Verify both remote hashes. Automatic deployment follows origin;
no separate redeploy. Minimal deployment identity/health observation may compare
the version and changed source hashes in the running containers, without dumping
environment values or logs/customer data. Report that outcome separately.

Full performance acceptance remains open under PLAN-056: a completed Coverage
response and cold/repeat behavior, Home's existing response target, matcher/history
write reduction and background Jobs behavior. Those checks need their bounded
external protocol and authorization; no unbounded original replay, forced Job,
cache flush, production benchmark or resource campaign is part of this push.

PLAN-056 remains active. This release is a correctness-tested recovery checkpoint,
not evidence of platform-wide performance recovery. The local active handoff owns
the subsequent release hash, push results and next acceptance action.
