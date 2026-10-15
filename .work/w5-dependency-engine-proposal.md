# W5: how findings relate (approach)

Status: approach for approval. Step 1 is built locally, uncommitted. Date: 2026-10-15.
Part of the central work queue plan (`central-work-queue-design.md`, item W5). This replaces the earlier draft.

## The problem

One real situation produces several findings. The queue shows each one, so an operator sees five rows where there is
one thing to do, or one thing to decide. We want the operator to see work items, without losing any fact.

## The model: three ideas, each with one job

1. **Same subject (automatic, no data).** Every finding has a subject: a computer, a software title, a software
   version, a source group. Any two findings with the same subject are related by construction. Every finding row and
   detail shows "N other findings on this computer" (or title, version, group), linking to them. Nothing is hidden and
   nothing is curated, so it is complete for every type, including types added later.
2. **Covers (curated, data).** A reviewed judgment: "once finding A exists, finding B adds no work of its own." B is
   then hidden from the default list and counted on A ("N hidden"). B stays a real finding with its own history, is
   still evaluated, and returns by itself when A clears and B is still true. This is the only relation that changes what
   the operator sees, so it is the only one that needs a table and a review.
3. **Evidence (a kind of covers).** Detail that supports another finding, such as each withdrawn source record under
   "no source reports this computer". It is covered, and the parent lists it when expanded, so nothing is lost.

The test that separates them: if the finding vanished from the queue, would the operator lose a decision or a fact they
need? No (a symptom or redundant detail): it is covered. Yes (a distinct fact, even with the same remedy): it stays
visible, and idea 1 links it to its neighbors.

## Covers: the pairs (12, all on the same computer)

| Parent | Covers |
|---|---|
| `device_missing_from_source` | `device_source_record_withdrawn`, `device_offline`, `stale_required_platform`, `missing_required_platform`, `windows_servicing_unknown`, `patching_stalled`, `reboot_pending` |
| `device_offline` | `stale_required_platform`, `patching_stalled`, `reboot_pending` |
| `patching_stalled` | `reboot_pending` |
| `missing_required_platform` | `windows_servicing_unknown` |

Measured on production 2026-10-14: about 1,940 findings covered by these pairs today. `device_never_patched`,
`patch_failing_repeatedly` and `device_unenrolled` are real facts that being offline or unreported does not cause, so
they are not covered; idea 1 links them to the computer's other findings.

Rules, each pinned by a test:
- The parent must be open, acknowledged, investigating, or paused on the same computer. A paused parent still covers
  (a computer on vacation should not bring its patching findings back). Resolved, excluded, or wontfix parents do not.
- Chains are allowed; a finding is counted under its root-most open parent, so "N hidden" always sits on a visible
  finding. Cycles and self-pairs are refused.
- Covering never lowers urgency: while a parent covers a more severe finding, the Issues page shows the parent at that
  severity (stored severity unchanged), and "N hidden" says how many are high.
- Covered findings never notify (no rule is enabled today) and are excluded from needs-attention counts.
- Facts about installed state (end-of-life OS, software findings) are not covered by an offline parent.

## Completeness

- Every finding is reachable through its subject (idea 1), so no pair list can leave one out.
- Every finding type is a root (nothing covers it) or a dependent of one or more parents; the admin page lists both, and
  a test fails if a table row names a type that does not exist or forms a cycle.
- Pairs outside the same computer (software version, title, source group) are deliberately not covered: those
  relationships are "same subject", handled by idea 1. If a software pair ever needs hiding, it gets its own scope and
  review.

## What changes where

| Step | Work | Migration |
|---|---|---|
| 1 (built) | `finding_type_dependencies` table, admin page, seed trimmed to the 12 covers pairs | 0295 |
| 2 | `record_assessment` adds a `parent_open` signal (always emitted); root attribution; new policy version with the rule, `offline_days` 7, the Stage 1 override removed, and the label "Computer not reported by any source" | 0296 |
| 3 | Issues page: "covered" state hidden by default; "N hidden (K high)" on the parent, expanding in place; parent shown at the covered severity; "N other findings on this subject" on every row; covered findings excluded from counts and handled in CSV | none |
| 4 | First production run: measure hidden counts per pair, time the parent lookup | none |

## Decisions made

- Covered findings are hidden by default; "N hidden" expands in place (A).
- `device_missing_from_source` is the parent of the withdrawn records.
- No separate "related" table: relatedness comes from the subject.

## Still open

- Severity of a vanished security agent.
- The 922 new stale-agent findings after the shorter offline window are not fully explained.
- Browser verification of the Issues page and the new admin pages; running the migrations against Postgres.
