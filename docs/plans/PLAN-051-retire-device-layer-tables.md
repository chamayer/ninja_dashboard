# PLAN-051 — Retire the device layer tables

**Status: ready.** Registered 2026-11-03 from the PLAN-012 follow-up review
(gate item 5). Defined, not started. Code changes, migrations, the archive,
dropping tables, commits, pushes and deployment each keep their gates.

## Goal

The three device layer tables and their history tables stop being written and
are retired, as ADR-0013 decided, without losing the data-quality Issues that
currently run in the same resolver step and without discarding recorded
history unannounced.

## Purpose check (why they exist and where that moved)

- ADR-0005 introduced `Asset`, `OSInstance` and `AgentInstance` as layer
  entities; ADR-0006 recast them as attribute buckets; ADR-0013 (accepted
  2026-08-05) superseded both: hardware and OS facts are attributes of the
  Computer (claims and effective values, `device_cache_projector`), and agent
  presence is a relationship (`device_agent_presence_current`). It names
  `assets`, `os_instances` and `agent_instances` "compatibility projections …
  droppable once consumers move".
- ADR-0013's planned rename of `assets` to `device_hardware` never happened;
  retirement makes it moot.

## Evidence (code and production read-only, 2026-11-03)

| Table | Rows | Size | Writes in about 13 days |
| --- | --- | --- | --- |
| `assets` | 6,827 | 4.4 MB | 739 inserts, 3 updates |
| `os_instances` | 6,729 | 4.3 MB | 738 inserts, 792 updates |
| `agent_instances` | 12,906 | 5.5 MB | 948 inserts |
| `asset_field_history` | 839 | 0.4 MB | 3 inserts |
| `os_instance_field_history` | 7,844 | 5.6 MB | 1,574 inserts |
| `agent_instance_field_history` | 0 | 48 kB | 0 |

- Readers: none. No reader in Operations Python, templates, SQL views, database
  functions or repository bootstrap; Metabase is retired (PLAN-008). No foreign
  key points at these tables. The Django models (`Asset`, `OSInstance`,
  `AgentInstance`, `*FieldHistory`) are referenced only in `models.py`.
- Findings' `subject_layer` / `subject_layer_entity_id`: zero rows use them.
- Database objects: triggers `audit_asset_fields`, `audit_os_instance_fields`,
  `audit_agent_instance_fields` and their functions
  `audit_*_significant_fields()` (migration 0055); change-history registry
  rows (`own_history` for the three tables, `history_store` for the three
  history tables).
- Writers, both in `ingest/identity/resolver.py`:
  - `_write_layer_entities_for_new_device` (called on promotion from
    `_create_device_for_group`): writes only the three tables.
  - `_sync_device_attributes` (each resolver cycle): its first part writes the
    three tables; **its second part raises the data-quality Issues
    `placeholder_serial`, `shared_serial`, `unmatched_source_group` (including
    a delete from `unmatched_source_groups`) and `placeholder_mac`**. Both parts
    share one transaction and one error handler, so a layer-sync failure
    currently also skips those Issues.
  - `_infer_form_factor` is used only by the promotion writer.

## Design

Two releases, so no running process ever writes to a dropped table.

**Release A — stop writing.**
1. Move the data-quality Issues out of `_sync_device_attributes` into their own
   resolver step with its own transaction and error handling, unchanged in
   behavior (same finding types, condition keys and closing rules).
2. Remove the layer propagation part, `_write_layer_entities_for_new_device`
   and its call, and `_infer_form_factor`; update the comments that describe
   the old order (resolver, `device_cache_projector`, migration 0056's note).
3. Tests: the data-quality step produces the same findings as before for
   synthetic inputs; nothing writes the layer tables.

**Between releases.** Read-only production check that the six tables receive
no writes (counters unchanged over at least one full day of resolver cycles).

**Release B — retire.**
1. Archive the six tables (data and definitions) before the drop, stored with
   the existing rollback archives under PLAN-034's retention decision.
2. Migration: drop the triggers, trigger functions, change-history registry
   rows and the six tables; remove the Django models (`DeleteModel`). The
   reverse recreates empty tables; restoring data uses the archive.
3. Pre-check on production read-only that no new dependency appeared.

**Follow-ups, not in this plan.** Remove the unused `agent_ids` plumbing in the
promotion path after PLAN-045 lands (it edits the same code). Retiring the
unused findings columns `subject_layer` / `subject_layer_entity_id` and
`idx_findings_layer_entity` is a separate change (many writers set them to
null). Amend ADR-0013 to record the retirement.

## Steps

| Step | Item | Gate |
| --- | --- | --- |
| 1 | Release A code and tests in a separate worktree, after confirming the data-quality step's current behavior with tests first. | Implementation approval |
| 2 | Release A release. | Commit and push approval |
| 3 | Read-only check: no writes to the six tables. | Read-only production approval |
| 4 | Archive; Release B migration; rehearse on a schema-only production clone. | Approval of the archive location and the drop |
| 5 | Release B release; read-only post-deploy check. | Push approval including the drop migration |

## Risks

- Moving the data-quality Issues must not change their condition keys or
  closing behavior; covered by tests before and after the move.
- PLAN-045 edits `ingest/identity/resolver.py` (promotion path); rebase
  release A after it lands.
- Dropping history tables discards recorded field history (ADR-0033); the
  archive keeps it retrievable.

## Related

ADR-0005, ADR-0006, ADR-0013 (decision), ADR-0033 (change history), PLAN-012
(found it), PLAN-008 (Metabase retired), PLAN-034 (archive retention), PLAN-045.
