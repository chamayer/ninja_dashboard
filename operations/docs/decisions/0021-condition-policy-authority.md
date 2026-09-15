# 0021 — Condition policy authority and shared runtime

Status: Proposed for the live conditions integration

## Decision

The Operations database is the runtime authority for condition policy. Policy
versions are stored immutably, one version is explicitly active, and every
assessment records the version and digest it used. Operations admin is the
governed surface for drafting, validating, reviewing, auditing, and activating
new versions.

The repository profile is bootstrap and shadow input only. The initial
migration seed is checksum-locked so changing it requires a new migration.
Live Operations and ingest code must load the active database document and
fail closed when no valid active policy exists.

The pure contracts, parser, and engine are shared from `shared/conditions`.
Operations and ingest retain service-specific PostgreSQL persistence adapters.
Compatibility imports may remain under the existing Operations module path.

## Enforcement

- Policy rows have immutable version identity and a single active selector.
- Runtime roles can read policy and write assessments, but cannot edit policy
  rows directly; admin changes use the governed Operations workflow.
- Bootstrap version and digest are checked during migration.
- The parser validates duplicate definitions, dependency references, cycles,
  effects, thresholds, classification, and complete registered type coverage.
- Missing or invalid active policy prevents eligibility evaluation.
- Assessment rows retain policy version, digest, participants, coverage,
  response, and reevaluation key separately from legacy finding handling.
- Both Docker images package the same pure shared engine.

## Consequences

Policy changes do not require a code deployment after the admin workflow is
available. Existing finding IDs, condition keys, evidence, operator handling,
notifications, and source-action references remain unchanged. Shadow reports
may compare an explicitly supplied Git profile, but they do not activate or
write policy.

The initial live migration and admin workflow require PostgreSQL validation
before policy gates or subscriber enforcement are enabled.
