# 0020 — Conditions foundation and non-mutating shadow evaluation

Status: Accepted for the foundation/shadow slice; live enforcement is not enabled.

## Context

Findings serve operator work, notification selection, and internal consumers.
Their current status also mixes observed truth, handling, and relevance.
Computer identity, collection coverage, and offline state can invalidate or
deprioritize dependent conclusions without proving that a problem was fixed.
The user approved an additive foundation and shadow comparison before any
change to live behavior, followed by a tested commit/push.

## Decision

1. Keep both legacy finding tables, IDs, keys, source-action references, and
   notification fingerprints unchanged. A shadow correlation identity includes
   tenant, physical row kind, technical type, and existing condition key, with
   the row ID as fallback. It excludes handling and participant membership.
   This is not a new persisted uniqueness constraint or episode migration.
2. Represent multiple participants as typed references with explicit roles.
   Their tenant is the assessment's visibility scope, not ownership assigned
   to global software reference data. Computer membership is admitted through
   the same-tenant current-device inventory. Legacy non-computer references
   remain legacy references, not newly verified generic entities.
3. Keep evaluation coverage and response eligibility independent of handling.
   Clearing requires successful, complete, fresh evaluation of the exact scope.
   The shadow runner cannot clear, acknowledge, suppress, enqueue, or dispatch.
4. Keep the 53-type classification and dependency mappings in a versioned JSON
   shadow profile. It is reviewed comparison input, not a production policy
   authority. An explicit alternative profile is supported without deployment.
   Validate duplicate types, unknown rules, cycles, effects and thresholds.
5. Start with identity gating, extended-offline attention suppression, and
   collection-completeness gating. Existing identity groups are provisional
   blockers. Their absence is not proof of readiness. Missing required source
   scope declarations remain unknown, even if unrelated snapshots succeeded.
6. Evaluate each participant separately. A blocked Computer attribution does
   not erase a global software fact. Candidate software fanout is explicitly
   labeled: it is not a replacement for the current exposure view's predicates.
7. Do not implement blanket severity suppression. Independent lower-severity
   conditions remain independent. Operator snoozes and suppressions persist;
   expiration alone does not establish the prerequisites for action.

## Enforcement

| Rule | Mechanism in this slice |
| --- | --- |
| No production mutations | Explicit PostgreSQL repeatable-read/read-only transaction, rollback on success, no apply flag and no imports of action/dispatch code |
| Tenant isolation | Required positive tenant argument, transaction-local tenant setting, tenant predicates on all scoped reads, same-tenant device membership |
| No silently truncated report | Bounded fetches fail when the row limit is exceeded; per-query statement timeout |
| No unknown-is-healthy | Explicit `unknown` readiness and missing-scope reasons; synthetic tests for missing and contradictory evidence |
| Stable references | Immutable contracts and status/membership/row-kind tests; no replacement of legacy IDs |
| Policy validation | Profile parser rejects invalid effects, unknown dependencies, cycles and duplicate definitions |
| Private evidence stays private | Reader selects IDs/metadata only; report outputs aggregate counts and technical types, never raw IDs, names, URLs or source payloads |
| No silent subscriber change | Opt-in management command only; no startup hook, scheduler, view, SQL view or existing evaluator modified |

## Consumers and compatibility

The comparison inventories Issues, Admin Health, entity pages, counts/health
history, software exposure, notification dispatch, digest, source actions,
merge/mapping workflows, and legacy/external consumers. It reports candidate
dependency impacts, not exact delivery or permission decisions. Enabled rule,
digest-route and pending source-action counts provide configuration context.

`v_device_software_exposure` and the materialized client-health history consume
findings independently. Legacy Agent Compliance dashboards use a different
schema and must not be silently repointed. External SQL consumers cannot be
proven absent by static inspection. Existing interfaces remain unchanged.

## Not implemented by this slice

Persisted participants/episodes, a universal identity-readiness authority,
required-source-scope declarations, production dependency policy storage,
cross-client operator presentation, UI enforcement, alert/action enforcement,
automatic scheduling, or historical lifecycle reinterpretation. Those require
the follow-up acceptance gate in the runbook, not a silent feature toggle.

No migration, role grant, new dependency, or default production behavior change
is required. The existing Dockerfile copies the entire application directory,
including the profile and command.
