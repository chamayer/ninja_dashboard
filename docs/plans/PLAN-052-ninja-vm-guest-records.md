# PLAN-052 — Ninja VM guest records: withdrawn volume and unmatched health rows

**Status: ready.** Registered 2026-11-04 from a PLAN-019 read-only count.
Defined, not started. Production reads, code changes, migrations, data
cleanup, commits, pushes and deployment each keep their gates.

## Goal

Explain, then fix if wrong, two anomalies in Ninja VM guest source records:

1. **Withdrawn volume.** Most Ninja VM guest device records are withdrawn.
   Decide whether that is normal VM churn or a collection or identity fault,
   and whether long-withdrawn VM records need a retention rule.
2. **Health rows without a matching device.** VM guest device-health rows
   outnumber VM guest device records. Health is a companion of the device
   record (PLAN-038, ADR-0051) and should match it one to one.

## Evidence (production read-only, 2026-11-04)

`entity_observation_current`, Ninja only:

| Record type | Namespace | Total | Present | Withdrawn | Withdrawn > 90 days |
| --- | --- | --- | --- | --- | --- |
| `vm.guest` | `device` | 2,704 | 698 | 2,006 | 605 |
| `vm.guest` | `device-health` | 3,453 | 841 | 2,612 | 53 |
| `vm.guest` | `vmware_guest_vmx_path` | 158 | 143 | 15 | 0 |
| `agent.rmm` | `device` | 5,118 | 4,675 | 443 | 78 |
| `agent.rmm` | `device-health` | 5,040 | 4,675 | 365 | 2 |

- For `agent.rmm`, present health equals present devices (4,675). For
  `vm.guest`, health exceeds devices by 749 in total and by 143 present.
- No record of any source is withdrawn for more than a year.
- Context: 6,846 Computers; 34,141 source records across all sources.

Not yet known: why the counts differ, whether the extra health rows have an
owner in `source_record_companions`, and what the withdrawn VM guests are
(deleted VMs, renamed or re-keyed guests, or collection gaps).

## Steps

| Step | Work | Gate |
| --- | --- | --- |
| 1 | Read-only production diagnosis: companion attachment of VM guest health rows (owner present, owner withdrawn, no owner); owner key values that do not match; withdrawn VM guests by age and by whether a `NODE_DELETED` event or a later record for the same machine exists | Read-only production approval |
| 2 | Decide per finding: writer or companion fix, identity fix, or a retention rule for long-withdrawn VM records (source records are not deleted automatically today; a rule needs its own decision) | User decision |
| 3 | Implement the decided fix with a focused test | Implementation approval; release approval names any migration |

## Out of scope

Hudu asset volume (more assets than Computers is expected; Hudu documents
more than computers). Presence history volume (PLAN-019 Step 4).
