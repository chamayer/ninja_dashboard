# 0054 — Attribute authority belongs to the record type

Status: Proposed
Date: 2026-11-03

## Context

The shared projector (ADR-0012) selects a Computer's effective values from
source claims by authority: whether a claim is eligible and its tier. ADR-0010
("Independent authority policies") made authority explicit and deny-by-default,
keyed by tenant, source instance, native record type and attribute, so that
second-hand sources stay observable but default to evidence-only, and
unconfigured attributes remain visible evidence without changing effective
values. Migration 0103 implemented this as `attribute_authority_policies`,
seeded once from a fixed table by record type for the instances that had
records then. Later decisions edited instance rows: hostname authority per
source instance (ADR-0034) was retired (ADR-0034 section 10, migration 0329), a
VM's hypervisor name stopped naming the Computer (ADR-0032, migration 0313), and
Ninja servicing evidence was added (0134). Nothing creates rules for a new instance, record type or
attribute, and the admin page is read-only.

A missing rule silently makes a claim ineligible. On 2026-11-03 two enabled
instances had no rules (AMROSE ScreenConnect, 4,779 active records on 4,169
Computers; R-U-ON, 728 records), and 764 of the 1,208 Computers at
`os_group = 'Unknown'` had an OS claim that was ignored and an
`os_unknown_coverage` Issue as a result.

Claims also store a copy of the rule (`authority_eligible`, `authority_tier`,
`authority_priority`) taken at projection time, as do relationship evidence
(0110/0111/0395) and OS-installation evidence (0153). A rule change does not
reach existing evidence; migration 0313 had to invalidate projection state by
hand.

## Options considered

- Add rule rows for the two instances: fixes today's gap only; the next
  instance repeats it.
- Copy default rules into each new instance when it is created: copies drift
  when a tier changes and still miss new record types and attributes.
- Defaults by record type with per-instance rules as the primary store: keeps
  the instance as the place authority lives and keeps policy copied onto
  evidence.
- Authority as a required property of the record type, attribute exceptions by
  record type, evidence without policy (selected).

## Decision

Proposed (2026-11-03; acceptance by the user after PLAN-046 step 1):

1. **Record-type authority is required data.** Each record type in
   `entity_types` defines whether its claims are eligible and their tier and
   priority. A record type cannot be registered without it, so no source
   instance or record type can exist without a rule.
2. **Exceptions are by record type and attribute.** A small admin-managed table
   holds the deviations (for example `vm.guest` power state at a higher tier,
   `vm.guest` hostname not eligible, retired hostname authority).
3. **Per-instance overrides exist only where evidence requires them.** PLAN-046
   step 1 compares current rules across instances of each record type. If none
   differ, per-instance rules are retired. A real difference the user confirms
   becomes an explicit, audited override; the outcome is recorded here before
   acceptance.
4. **Evidence carries no policy.** Claims, relationship evidence and
   OS-installation evidence stop storing authority. Effective and relationship
   selection read authority at selection time; the selection signature includes
   the rule version, and a rule change queues re-selection for the affected
   (record type, attribute) keys.
5. **Second-hand sources stay evidence-only (ADR-0010).** Whether a source
   instance reports first-hand is an explicit, audited property of the instance,
   not the absence of a rule. A second-hand instance's claims are evidence-only
   whatever their record type; a new instance must declare it when it is
   configured (PLAN-026). This keeps ADR-0010's protection while removing
   "no rule" as a state.
6. **Unconfigured attributes stay evidence (ADR-0010).** An attribute without a
   source field mapping is still not selected; record-type authority applies
   only to mapped attributes.
7. **Operators manage the rules** in Operations, with a reason and change
   history (ADR-0033); the read-only admin page is replaced.
8. **Scope.** This decision covers attribute authority and the relationship
   evidence that copies it. Identity policy (`identity_authority_policies`,
   ADR-0010 `may_establish_identity` / `may_create_canonical`) has the same
   per-instance keying; PLAN-046 step 1 checks whether it has the same gap, and
   any change to it is a separate decision.

## Rationale

Trust in a report ("an RMM agent's OS") is a property of the kind of evidence,
not of the server it came from. Keying authority by record type makes coverage
complete by construction, so a new instance is weighed from its first record.
Keeping policy out of evidence makes a rule change effective without
re-projection, the same separation ADR-0053 applied to association. One rule set
per record type keeps ADR-0012's single shared projector authoritative.

## Consequences

- Required: a migration adding record-type authority and the exception table,
  seeded from current rules; projector changes so evidence no longer stores
  authority; rule-change triggers queuing re-selection; an Operations editor;
  rehearsal of the re-selection drain (about 237,000 effective values).
- Enforced by a NOT NULL authority on `entity_types` and the selection join,
  not by readers.
- Prohibited: adding authority rules per source instance without the override
  path and its audit.
- Selected values change where instances had diverging rules; PLAN-046 step 1
  lists them before release. AMROSE ScreenConnect and R-U-ON evidence becomes
  eligible according to its record type unless the user sets an exception.
- A missing rule is no longer a state to detect. Sources shows deliberate
  ineligibility, second-hand instances and disabled exceptions as a guard.
- Every existing instance needs a first-hand/second-hand value; PLAN-046 step 1
  proposes one per instance from current rules for the user to confirm.

## Supersedes or superseded by

Amends ADR-0010 "Independent authority policies": attribute authority is keyed
by record type (with exceptions and, where evidenced, instance overrides)
instead of source instance, and deny-by-default for second-hand sources becomes
an explicit instance property. Supersedes the per-instance authority seeding of
migration 0103. Refines ADR-0012 (shared projector). Carries forward the
exceptions decided in ADR-0032 (VM hypervisor name not authoritative) and
ADR-0034 section 10 (hostname authority retired). Rule edits follow ADR-0033.
Related: ADR-0050, ADR-0053, PLAN-046.
