# PLAN-046 — Authority belongs to the record type

**Status: ready.** Registered 2026-11-03 from the PLAN-012 post-release check.
Defined, not started. Each step below needs the user's approval where marked;
production writes, migrations, commits, pushes and deployment keep their usual
gates.

**Decision record:** [ADR-0054 — Attribute authority belongs to the record
type](../../operations/docs/decisions/0054-authority-belongs-to-the-record-type.md)
(Proposed). The ADR is the authority for the design; this plan owns steps,
evidence and validation.

## Goal

Every source record's claims are weighed by a rule that exists by construction.
Adding a source instance, a second instance of a source, or a record type can
never silently leave its evidence without authority, and changing a rule takes
effect without re-projecting evidence.

## Problem (production, read-only, 2026-11-03)

- Authority rules (`attribute_authority_policies`) are keyed by **source
  instance**, record type and attribute. Migration 0103 seeded them once from a
  fixed table by record type (`agent.rmm` 300, `agent.edr` 250,
  `agent.remote_access` 225, `network.device`/`vm.host`/`org` 200, `vm.guest`
  150, `monitor.target` 100, `cmdb.asset` 50) for the instances that had records
  then. Later migrations edited instance rows (0134 inserted a Ninja row; 0313
  made `vm.guest` hostname ineligible; 0329 disabled hostname rows).
- Nothing creates rules for a new instance, record type or attribute, and the
  admin page is read-only. Two enabled instances have none: AMROSE ScreenConnect
  `e60e2a98…` (4,779 active records, 4,169 Computers) and R-U-ON `e9300f3f…`
  (728 records). Their claims are stored as ineligible.
- Result: 764 of the 1,208 current Computers at `os_group = 'Unknown'` have an
  OS claim that is ignored, and each gets an `os_unknown_coverage` Issue
  (example: `nvr241e`, created 2026-11-02 23:59 from AMROSE ScreenConnect).
- Claims store a copy of the rule (`authority_eligible`, `authority_tier`,
  `authority_priority`) taken at projection time. A rule change does not reach
  existing claims; 0313 had to invalidate projection state by hand ("Claims carry
  the policy at projection time"). Relationship evidence (0110/0111/0395) and OS
  installations (0153, `ingest/os_installations.py`) carry the same copy.

## Root cause

1. Authority is stored at the wrong grain: trust in "an RMM agent's OS report"
   is a property of the kind of evidence, not of the server it came from.
2. Evidence carries a copy of policy, so policy changes need re-projection.
3. A missing rule is a silent default (ineligible), not an impossible state.

## Design

Summary of ADR-0054; on any difference the ADR governs.

1. **Record-type authority, complete by construction.** Each record type in
   `entity_types` defines its authority (eligible, tier, priority) as required
   data. A record type cannot exist without it.
2. **Attribute exceptions by record type.** A small admin-managed table holds
   exceptions per (record type, attribute), e.g. `vm.guest` power state 300,
   `vm.guest` hostname ineligible, retired hostname authority.
3. **Instance overrides only with evidence.** Step 1 compares current rules
   across instances of each record type. If none differ, per-instance rules are
   retired. Any real difference becomes an explicit, audited override shown to
   the user before it is kept.
4. **Evidence carries no policy.** Claims, relationship evidence and OS
   installation evidence stop storing authority. Effective selection reads it at
   selection time; the selection signature includes the rule version, and a rule
   change queues re-selection for the affected (record type, attribute) keys.
5. **Second-hand sources stay evidence-only.** ADR-0010's deny-by-default
   protection becomes an explicit, audited first-hand/second-hand property of
   each source instance, declared when the instance is configured (PLAN-026).
   Unmapped attributes stay evidence only.
6. **Operators manage the rules** in Operations (record-type authority and
   exceptions, and overrides if any), with reason and change history
   (ADR-0033), replacing the read-only admin page.
7. **Guard, not defense.** Sources shows, per instance and record type, which
   mapped attributes are deliberately ineligible or disabled, and which
   instances are second-hand. "No rule" cannot occur.
8. **Decision record.** ADR-0054 amends ADR-0010 "Independent authority
   policies", refines ADR-0012, carries forward the ADR-0032 and ADR-0034
   exceptions, and records the evidence/policy separation. Identity policy has
   the same per-instance keying and is out of scope (step 1 checks it).

## Steps

| Step | Item | Gate |
| --- | --- | --- |
| 0 | Work in a separate git worktree and branch from `origin/master`; do not touch the uncommitted PLAN-042–045 work in the main checkout. Number migrations after PLAN-045's 0401–0403 and rebase when those land. | — |
| 1 | Read-only production inventory: for each record type and attribute, are rules identical across instances; record types and attributes with no rule; a proposed first-hand/second-hand value per instance from current rules; whether `identity_authority_policies` has the same gap; counts of claims, effective values, relationship and OS-installation evidence that each change would re-select. | Read-only production approval |
| 2 | Complete ADR-0054 with step 1's outcome (overrides kept or retired, first-hand/second-hand per instance, R-U-ON exceptions) and the exact rule table; the user accepts or amends it. | User decision on R-U-ON trust, instance classification and any overrides; ADR-0054 accepted before step 3 |
| 3 | Migration: record-type authority columns, exception table, seed from current rules, retire instance rules (or convert real differences to overrides), rule-change triggers queuing re-selection. Read real constraints first; pre-check any assertion on production read-only. | Migration review |
| 4 | Projectors: claim, relationship and OS-installation projectors stop writing authority; effective and relationship selection read it at selection time. Keep one copy of each rule. | — |
| 5 | Operations: rule editing with reason and change history; Sources guard view. | — |
| 6 | Tests: unit and focused PostgreSQL; rehearsal on a schema-only production clone (as PLAN-038 and PLAN-012), including a full re-selection drain with timing and lock observation. | Rehearsal approval |
| 7 | Release: VERSION/CHANGELOG, release check, push to both remotes, read-only post-deploy verification. | Push approval including the migration |

## Validation and acceptance

- A new source instance's records are weighed from their first projection, with
  no rule rows added for it.
- After release, the AMROSE ScreenConnect Computers that only lacked rules get OS
  values, and their `os_unknown_coverage` Issues close through the normal
  evaluator path.
- A rule change in Operations re-selects only the affected keys, with history.
- Computers with eligible evidence before the change keep the same selected
  values unless an intended rule differs (diff reported before release).

## Risks

- Re-selection volume: about 237,000 effective values and 408,000 active
  claims; the drain must be bounded and measured in the rehearsal.
- The effective projector's signature and conflict logic change; ADR-0012's
  single shared projector must be preserved.
- PLAN-045 is changing related ingest and Operations files; rebase and re-test
  after it lands.
- Selected values may change where instances had diverging rules; step 1 lists
  them first.

## Related

ADR-0054 (this plan's decision), ADR-0010 (amended: independent authority
policies), ADR-0012 (shared projector), ADR-0032 and ADR-0034 (exceptions carried
forward), ADR-0033 (rule changes recorded), ADR-0050, ADR-0053; PLAN-012 (found
it), PLAN-025 (added the AMROSE ScreenConnect instance), PLAN-026 (source
configuration UI declares first-hand/second-hand).
