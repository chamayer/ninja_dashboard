# 0043 — One finding: "One machine or two?"

Status: Accepted (2026-10-23)
Date: 2026-10-23

## Context

Six finding types ask, from different evidence, whether Computer records
describe one machine or several, split across two Issue groups ("Computer
identity" and "Duplicate computers"):

| Type | Question it asks | Open 2026-10-23 |
|---|---|---|
| `duplicate_device_records` | Same name in one client, nothing links or separates them | 45 |
| `identity_conflict` | A record's name matches several Computers | 7 |
| `computer_name_collision` | A rename would give two Computers one name | 5 |
| `shared_serial` | Two Computers report one serial but were not merged | 2 |
| `two_machines_on_one_computer` | One Computer holds two machines' records | 5 |
| `duplicate_platform_record` (admin) | Two records of one source on one Computer | 82 |

Measured 2026-10-23: 190 Computers carry these findings and 23 carry two or
more types (mostly `duplicate_device_records` with `identity_conflict`,
`computer_name_collision` or `duplicate_platform_record`). An operator sees
the same pair several times, each with different actions. ADR-0040 settled
the client side the same way ("Computer under the wrong client?").

## Options considered

- Keep the six types and only group them on one page.
- One finding per group of Computers with a row per piece of evidence and the
  actions that answer the one question.
- Merge everything, including the per-source record duplicates.

## Decision (proposed)

1. One finding type, "One machine or two?", subject the group of Computers
   (one per connected group, keyed by its members as today), with a row per
   piece of evidence: shared serial or VM UUID (strong, "one"), differing
   serials or two agents online at once (strong, "two"), same name or a
   rename collision (weak, shown, never decisive alone).
2. Actions, on one, several or all selected groups: **Merge** (refused while
   strong "two" evidence exists), **Confirm separate**, **Split as proposed**
   (for one Computer holding two machines). Each is the existing recorded
   operation (`merge_computers`, `confirm_computers_separate`,
   `split_computer_records`); merges can be split again from the Computer
   page.
3. It replaces `duplicate_device_records`, `identity_conflict`,
   `computer_name_collision`, `shared_serial` and
   `two_machines_on_one_computer`; their open findings close with the reason.
   `duplicate_platform_record` (two records of one source on one Computer) is
   a different question, a source hygiene issue, and stays.
4. One Issue group, "Computer identity".

## Rationale

The operator answers one question per group of Computers, with all the
evidence and the right actions in one place, as for client ownership.

## Consequences

- Migration: the type, the policy version, closing the replaced types.
- The identity evaluator builds groups from all evidence at once; existing
  decisions (`identity_separate`, `identity_excluded_records`) keep working.
- To measure before building: how many groups result, and that no group mixes
  clients (ADR-0040's finding owns that).

## Supersedes or superseded by

Extends ADR-0032 and ADR-0034's identity findings.
