# PLAN-047 — Write only what changed

**Status: ready.** Registered 2026-11-03 from the PLAN-012 follow-up review of
table bloat. Defined, not started. Production writes, migrations, table
compaction, commits, pushes and deployment keep their usual gates.

## Goal

Every projector, evaluator and refresh writes a row only when its content
changes. Table size tracks live data, autovacuum stops running thousands of
times per table, and runs spend CPU on changes rather than rewrites.

## Evidence (production, read-only, 2026-11-03)

Counters since the Postgres start on 2026-10-21 (about 13 days):

| Table | Live rows | Writes | Pattern |
| --- | --- | --- | --- |
| `cve_match` | 648,872 | 36.5 M inserts, 37.5 M deletes | rebuilt about 4 times a day |
| `entity_relationship_evidence_current` | 117,955 | 27.2 M updates | all rows rewritten per projection |
| `software_device_readiness` | 432,852 | 25.7 M updates | all rows rewritten |
| `device_requirement_state` | 20,385 | 9.7 M inserts, 9.7 M deletes | `write_device_requirement_state` deletes and re-inserts every row with `evaluated_at = now()` |
| `entity_relationship_evidence_history` | 64,755 | 13.6 M updates | rewritten |
| `operating_system_installation_source_identities` | 99,406 | 13.6 M updates | rewritten |
| `software_installations_current` / `_history` | 684,947 / 1,560,912 | 13.3 M / 13.0 M updates | rewritten |
| `device_session_current`, `device_patching_scope_current`, `device_agent_presence_current` | 6,371–23,964 | 2–6 M inserts and deletes | materialized views refreshed concurrently; the session view includes `last_observed_at` (poll time), so every row changes per refresh |
| `condition_assessments`, `finding_state`, `findings` | 254,344 / 176,835 / 618,602 | 9.3 M / 6.8 M / 5.5 M updates | evaluation rewrites |
| `entity_observation_current` | about 78,000 | 3.5 M writes | upsert on newer `observed_at` rewrites wide JSON rows to advance timestamps; 1.57 GB heap plus 1.1 GB TOAST |

## Root cause

Writers replace what they own on every run instead of applying the difference:
delete-and-insert, unguarded `UPDATE`, full materialized-view refreshes, and
per-run timestamps (`evaluated_at`, `last_observed_at`, `last_seen_at`) stored
on content rows so every row always differs.

## Approach

- For each writer, write only rows whose content differs (`IS DISTINCT FROM`
  guards, upsert plus targeted delete instead of delete-and-insert).
- Move per-run timestamps off content rows: a run-level "evaluated at" record,
  or a narrow presence/heartbeat row separate from the wide content row.
- Replace materialized views whose rows change on every refresh with
  incrementally maintained tables or with views over already-current data.
- Keep results identical; readers that show "evaluated at" or "last seen" keep
  their meaning from the run-level or presence record.
- Compaction (`VACUUM FULL` or repack) only after writes are fixed and re-measured,
  per table, with separate approval (exclusive lock).

## Steps

| Step | Item | Gate |
| --- | --- | --- |
| 0 | Work in a separate git worktree and branch; the main checkout holds another session's in-progress work. | — |
| 1 | Writer inventory from code (local, read-only): for each table above, the writer, its change guard, which columns change every run, and the readers of those columns. | — |
| 2 | Fix by volume: `cve_match`; relationship evidence and history; software readiness and installations; `device_requirement_state`; session/patching/presence views; condition and finding state; observation timestamps. One change and tests per writer. | Migration review per writer |
| 3 | Rehearse migrations on a schema-only production clone where a function or trigger changes. | Rehearsal approval |
| 4 | Release; re-measure the counters over a comparable window (read-only). | Push approval including migrations |
| 5 | Decide per table on one-time compaction from the new measurements. | Separate approval per table |

## Validation and acceptance

- Per writer: unchanged input produces zero row writes (tests), and changed
  input produces the same results as before.
- Production: write counters per run fall to the volume of real changes; dead
  rows stay a small fraction of live rows between autovacuums.
- No reader loses an "evaluated at" or "last seen" value it shows today.

## Related

PLAN-041 (host CPU; `cve_match` matcher), PLAN-014 (requirement verdicts and
`evaluated_at`), PLAN-019 (data pipeline correctness and retention), PLAN-012
(found it), ADR-0035 (stored requirement verdicts), ADR-0012 (shared projector).
