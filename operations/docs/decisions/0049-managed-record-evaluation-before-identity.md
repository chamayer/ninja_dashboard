# 0049 — Managed source-record evaluation before identity completion

Status: Accepted by the user 2026-10-29 (design revision 8, after independent review).
Acceptance covers the design decisions only. Runtime policy changes when the
approved implementation ships; implementation and production execution need
separate authorization.

## Decision

Every received record is a managed/evaluable native `source_record` with stable
UUID/natural identity from intake, independent of Computer/class/client resolution.
A comparison case is a native mechanism subject, not a canonical entity or proof
of shared physical identity. ADR-0012's evidence/projector and tenant rules remain.

1. **Authority:** `entity_source_links` plus history is the sole confirmed-association
   authority. One protected procedure projects observation `device_id`; convert all
   writers and revoke direct writes in a coordinated, reviewed handoff. Preserve
   existing canonical IDs and explicit attachment/separation decisions.
2. **Independent evaluation:** code-defined rules with validated config and a recorded
   rule/config revision evaluate their own inputs. Missing role/context yields precise
   unknown for that rule. Purpose/age defaults remain unknown; no automatic cleanup.
   Names and MACs are evidence, never sufficient proof by themselves; unresolved
   identity ambiguity is not broken by recency. ADR-0032/0048 amendments retain
   these conservative identity and qualified replacement/staleness directions.
3. **Freshness:** keep a coarse shared tenant guard for input-only writes and exclusive
   guard for graph/publication/actions. Input writers atomically advance one protected
   tenant generation; publication/actions validate it and relevant versions after
   locking. One assessment/publisher worker, indexed neighbor enqueue and a durable
   conservative refresh fallback replace per-key lock plans/counters. A target-only
   version cannot detect comparison-universe changes. Validate load before rollout.
4. **Simple cases:** one qualified question/dimension per shared-key case, with a
   finding and directly qualifying members. Related cases are shown side by side;
   joining M adopts no other keys. No combine/split/redirect/anchor-repointing or
   new Covers matcher. Audited duplicate references preserve history, prevent
   immediate recreation while valid, and never mean verified correction.
5. **Notifications:** all new native source-record/case type keys are non-alertable.
   Keep legacy finding IDs, types, fingerprints, producers and dispatcher behavior;
   resolve exact correction ownership before adding potentially duplicate tasks.
   Do not add source context to legacy payloads or weaken restricted-record access.
6. **Reassessment/rollout:** preview, review and apply current authorized association
   dispositions without a blanket reset. Use an approved maintenance window and
   abort/recovery checkpoint for incompatible authority changes; resume intake
   before fleet evaluation. Compatible additive changes may deploy normally only
   after old/new writer compatibility is demonstrated. PLAN-003 retains its own
   common-store coordination and approval gates.

## Explicit amendments to earlier scoped directions

| Earlier ADR-0049 direction | Revision 8 disposition |
| --- | --- |
| Decision 1 association authority/reassessment | Retained; remove notification cutoff/sweep coupling and invented drain target |
| Decision 2 lock order | Retain tenant-before-row ordering and shared/exclusive guard; remove bucket/anchor advisory plans, ticket options and numeric throughput/hold targets |
| Decision 3 fresh publication | Retained with coarse tenant input generation, current rule/config revision and action checks |
| Decision 4 inclusive combined investigations/redirects | Narrow initial scope to one-key related cases; combining deferred to PLAN-033 |
| Decision 5 mixed notification suppression/context | Deferred with new notifications to PLAN-034; access controls remain required now |
| Decisions 6–7 activation baseline/material release/delayed sweep | Deferred to PLAN-034; no replacement first-opened-time policy is approved |

| Decision 3 shared guard for input-only writes | **Amended R4-1 (user, 2026-10-30):** intake, association and presence writers take no guard. An observation trigger admits the subject and enqueues work in the intake transaction. A deferred subject trigger advances the tenant generation at commit. Publication holds the exclusive guard plus a share lock on the generation row, so input commits wait one bounded batch ([design §3/§7.2](../plans/PLAN-004-source-record-final-design.md#72-minimal-locking-and-bounded-transactions)) |
| Decision 3 "validate load before rollout" | **Waived R4-2 (user, 2026-10-30):** no representative load run. Watch ingest timings, queue depth and oldest dirty revision after release |

These amendments supersede the earlier proposed delivery contract for this design
revision. They do not rewrite accepted deployed runtime policy. Stable subject/case
IDs, normal finding history and assessment revisions preserve room for follow-ups.

## Rationale, alternatives and follow-ups

A record waiting for identity is not independently managed; a provisional Computer
per record fabricates identity. A third attachment table duplicates existing authority.
Reject those alternatives. Keep the native-subject distinction and one authority.

Per-key locking/counters, a policy JSON engine, case-combine lifecycle and notification
conversion/activation subsystems exceed the initial need. Revisit only with concrete
workload or operator evidence, not by restoring the previous design wholesale.

- [PLAN-033](../plans/PLAN-033-source-record-case-combining.md): case combining.
- [PLAN-034](../plans/PLAN-034-source-record-notifications.md): source-record alerts.
- [Operations backlog](../../TODO.md): smaller evidence-driven optimization options.

## Enforcement and review

[Final design](../plans/PLAN-004-source-record-final-design.md) owns schema, writer
inventory, queue/generation/guard contract, RLS, action checks, three-stage rollout
and acceptance. Privileges/constraints/protected entrypoints enforce these rules;
prose is not runtime evidence. Implementation, migration, production reassessment,
source mutation, commit and deployment remain separately authorized.
