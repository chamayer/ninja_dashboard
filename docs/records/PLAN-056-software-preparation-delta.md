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
