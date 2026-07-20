# Active Operations work plan

Track: **Device identity + layered entities (v1)** — implementation of
`operations/docs/decisions/0005-device-identity-and-layered-entities.md`.

## Status

- Active — Slices 1, 2, and 3 code complete. Not committed, not
  applied to any database. Follow-up retirement of
  `identity_candidates` and audit of other side tables live in
  `operations/.work/backlog.md`.

## Goal

Land the layered-entity model as an additive change: new canonical layer
entities (`Asset`, `OSInstance`, `AgentInstance`) with their own effective
windows, backfilled from current `Device` state, with the existing collapsed
matview surface preserved. Flat `Device` attribute columns stay as a
denormalized current-state cache kept in sync via the ingest write path.

## Scope

- In:
  - Migrations 0050 (schema), 0051 (backfill of `Asset` and `OSInstance`
    only — see decisions).
  - `findings.subject_layer` + `subject_layer_entity_id` back-reference
    columns.
  - Per-layer significant-field audit tables.
  - Ingest resolver rewrite to emit layer-entity extend/open/close ops
    (slice 2).
  - Form-factor "unknown until positive evidence" rule on the Asset layer
    (slice 2).
  - Identity-conflict finding for hostname-only observations (slice 2).
- Out (v1):
  - Retiring flat `Device` attribute columns.
  - Forced UI or evaluator cutover.
  - Full field-level audit (only significant fields captured in v1).
  - Cross-Device operator-authored successor linking UI.
  - Metabase question edits (Metabase is deprecating).
  - New `v_device_current` view — existing `operations.v_device` (0042)
    already provides the collapsed surface and stays as-is.
  - `AgentInstance` backfill — slice 2 resolver is the authoritative
    writer; backfilling would fabricate first_seen timestamps.

## Files involved

- New: `operations/apps/core/migrations/0050_layered_entities_schema.py`
- New: `operations/apps/core/migrations/0051_layered_entities_backfill.py`
- Modified: `operations/apps/core/models.py` — added `Asset`, `OSInstance`,
  `AgentInstance`, `AssetFieldHistory`, `OSInstanceFieldHistory`,
  `AgentInstanceFieldHistory`, `Finding.subject_layer` +
  `subject_layer_entity_id`.
- Pending slice 2: `ingest/identity/resolver.py`.
- Pending: `VERSION`, `CHANGELOG.md` (0.64.0 for slice 1; 0.65.0 for slice 2).

## Steps

- [x] Slice 1: Update `models.py` with layer entity Django models + audit
      models + `Finding.subject_layer` fields.
- [x] Slice 1: Migration 0050 — schema (tables, RLS, indexes, finding
      columns). No cutover of existing consumers.
- [x] Slice 1: Migration 0051 — backfill open-window `assets` and
      `os_instances` rows from current `Device` state. Idempotent.
- [x] Slice 1: `python manage.py check` clean. `ruff check` clean.
      `makemigrations --dry-run` shows only pre-existing unrelated
      Meta-option drift. Version 0.64.0. CHANGELOG.
- [x] Slice 2: `ingest/identity/resolver.py` — `_infer_form_factor` fixed
      (dropped `agent → physical`), matching SQL branch in
      `_sync_device_attributes` dropped, `_write_layer_entities_for_new_device`
      helper opens Asset + OSInstance + AgentInstance rows on Device
      promotion, attribute sync propagates form_factor / os_name /
      os_family / os_group into the current-window layer rows and
      opens missing AgentInstances for agent-nature observations.
- [x] Slice 2: `ruff check ingest/identity/resolver.py` clean. Syntax
      check clean. Django check clean. Version 0.65.0. CHANGELOG.
- [x] Slice 3: `identity_conflict` FindingType seeded (migration 0052).
      `_maybe_create_candidate` emits a standard Finding into
      `operations.findings`, deduplicated by
      `condition_key='identity_conflict:{hostname}'` via ON CONFLICT
      DO UPDATE on the partial unique index. Legacy
      `identity_candidates` write retained during transition — its
      admin UI has live consumers. Retirement is a separate backlog
      track (`operations/.work/backlog.md` → "Consolidate side
      tables"). Version 0.66.0. CHANGELOG.
- [x] Memory rule saved: findings live in the standard table only.
      See `memory/feedback_findings_single_surface.md`.

## Decisions

- Layer entities carry `device_id` + `effective_from` + `effective_to`
  directly (no separate windows table). Partial unique index enforces
  at-most-one open window per (Device, layer) except `AgentInstance`
  which is partial unique on (Device, agent) since multiple products
  coexist.
- Flat `Device` attribute columns stay as cache; updated by the ingest
  write path (not by a database trigger) since the resolver is the only
  current writer.
- Audit tables capture significant fields only (form_factor, serial,
  vm_uuid, os_name, os_version, agent_version, install_token). Heartbeat
  churn is excluded.
- `operations.v_device` is the primary consumer surface and stays as-is.
  Existing matviews (`device_session_current`,
  `device_agent_presence_current`, `device_patching_scope_current`)
  remain in place; re-sourcing them from layer entities is deferred out
  of v1.
- Backfill covers only `Asset` and `OSInstance`. `AgentInstance` is
  slice 2 (resolver is the only reliable writer for install-lifetime
  boundaries).

## Validation

- `python manage.py check`
- `python manage.py makemigrations --dry-run` (verify no unintended model
  drift)
- `ruff check .` and `ruff format --check .`
- Manual migration plan review — RLS on new tables, effective-window
  constraints, backfill idempotency.
- Focused smoke: existing devices listing still renders (`v_device`
  unchanged).

## Current checkpoint

- Stack version 0.63.0 (to be bumped to 0.64.0 when slice 1 lands).
- ADR-0005 Accepted 2026-07-20 (v1 execution).
- Slice 1 code written; validation pending.
- Slice 2 not started.

## Remaining blockers

- Slice 1 validation not yet performed (`python manage.py check`,
  `ruff check`, `makemigrations --dry-run`).

## Next action

- Run slice 1 validation and, if clean, bump VERSION + CHANGELOG for
  0.64.0.
