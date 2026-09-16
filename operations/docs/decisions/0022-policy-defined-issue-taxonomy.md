# 0022 — Policy-defined issue taxonomy

Status: Accepted; deployment validation pending

## Decision

The active condition policy’s per-definition category, type, and label are the
authority for the Issues taxonomy. Migration 0164 promotes six stable category
keys: `computers`, `documentation`, `records_matching`, `security_software`,
`system_health`, and `updates_support`.

The queue derives category membership from policy definition names rather than
maintaining a separate hardcoded category map. Legacy category values remain
accepted and redirect to the canonical policy key while preserving other query
parameters.

## Consequences

Older links remain usable during rollout, while new links converge on the
policy-defined taxonomy. The migration creates an immutable policy version and
activates it atomically; rollback reactivates `conditions-shadow-1` without
rewriting historical assessments or finding identities.

Production validation must confirm the migration against the deployed finding
registry and verify category counts with representative retained and eligible
findings.
