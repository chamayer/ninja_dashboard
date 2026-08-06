# 0014 — Source links are derived from observations

Status: Accepted
Date: 2026-08-06

## Context

`operations.device_links` was the last "competing attachment authority" named
by ADR-0010 phase E6. Six code paths wrote it directly: three in the identity
resolver, one in the fast path, one in the Ninja device collector, and the
device merge view. `operations.entity_source_links` recorded the same
attachment, derived from observation evidence by
`operations.sync_entity_source_links_from_observations()`.

Two authorities for one fact produced a defect rather than mere redundancy.
The collector's `_sync_operations_device_links` maintained `last_seen_at` and
`missing_since` under a `WHERE s.name = 'Ninja'` filter, so both columns were
only ever current for one of four sources. Measured against production
2026-08-05: 209 links reported an agent present that had stopped reporting
6-23 days earlier (SentinelOne 137, LogMeIn 65, ScreenConnect 7, Ninja 0), and
`last_seen_at` was frozen on 3,026/3,031 LogMeIn, 1,013/1,013 ScreenConnect
and 4,346/4,351 SentinelOne links against 0/5,884 Ninja. Because
`device_missing_from_source` resolves from `missing_since`, that finding could
not resolve correctly outside Ninja.

Three questions arose during the retirement that recur beyond it, and are
recorded here rather than left in a migration docstring.

## Options considered

- Keep `device_links` and fix the Ninja-only filter.
- Replace the table with a compatibility view of the same name, and rewrite
  readers later.
- Retire the table and repoint every reader in the same release.

## Decision

1. **Attachment is derived from observation evidence.** `entity_source_links`
   is the single attachment surface, and `operations.v_device_source_link` is
   its device-scoped read model. No producer — connector, resolver, evaluator
   or UI action — writes attachment directly.
2. **A retired relation gets no compatibility alias.** Readers move in the same
   release that retires it.
3. **`device-health` is a companion namespace, not an independent link.** Any
   `entity_source_links` consumer that counts or joins per device must exclude
   it, alongside `asset`.
4. **A view read by ingest must be `security_invoker = true`.**

## Rationale

**On (1)** — this is the ADR-0012 rule applied to attachment: a source
assertion is evidence, never state. The defect above is what the general rule
prevents. A local fix to the Ninja filter would have left two writers of one
fact and the next divergence unprevented.

**On (2)** — a compatibility view was built first and rejected. It had to
collapse the per-namespace rows, which meant emitting `match_method`,
`match_confidence` and `external_name` as invented constants and minting a
synthetic primary key. It was also a ~365x performance regression: building
`device_patching_scope_current` measured 247 ms against the original table,
over 90 s through the compatibility view, and 278 ms through the flat view
that shipped. The aggregate planned *identically* to the fast form — same
nodes, same cost estimate — so only execution against production exposed it.

**On (3)** — this is what made the aggregation unnecessary, and it is the item
most likely to catch someone later. `entity_source_links` records one row per
external namespace. Ninja is the only source with two, `device` and
`device-health`, and `device-health` is the health-poll companion of the same
records, covering the same five entity types; migration 0098 had already
excluded it from device presence for the same reason. Excluding it yields
exactly one row per `(tenant, source, external_id)` with no grouping.
Verified against production: flat and aggregated forms produce identical row
sets (14,286 each, zero rows on either side of the difference), zero duplicate
keys, and — compared row by row — zero disagreement on `missing_since`
presence and zero on `last_seen_at`. A consumer that forgets this exclusion
silently double-counts Ninja devices; the fan-out is about 1.7x overall.

**On (4)** — ingest connects as `ninja`, a BYPASSRLS superuser, and refreshes
matviews with no `operations.tenant_id` GUC set. A default view evaluates
row-level security as its own owner, so it would lose that BYPASSRLS, match
the tenant policy against a NULL GUC and return zero rows — silently emptying
whatever reads it. `security_invoker` evaluates RLS as the caller, reproducing
the semantics of the table it replaces. `v_device` already followed this.

## Consequences

- `operations.device_links`, the `DeviceLink` model and its writable admin no
  longer exist. `DeviceSourceLink` is unmanaged and read-only, and
  `operations_app` holds `SELECT` only, so the write path is closed by
  privilege rather than by convention.
- `match_method` and `match_confidence` are now whatever the sync records
  (`compatibility` for every row today). `external_name` is gone; it was
  write-only, and nothing read it.
- Device merge moves observations and lets links follow on the next sync.
  Writing `entity_source_links` directly would repoint the current row while
  leaving the open `entity_source_link_history` interval attributing the link
  to the tombstoned device, losing when and why attachment moved.
- Anything needing attachment inside a promotion transaction must read
  `entity_observation_current.device_id`, not the derived link table, which is
  only rebuilt later in the cycle. The resolver promotion guard and fast-path
  step 1 both do.
- Presence is now maintained for every source, so
  `device_missing_from_source` resolves correctly for all four. Stale-but-live
  links measured 0 after cutover, against 8,316 before.
- A new per-device source relation must decide explicitly whether its
  namespace is an identity link or a companion, per (3).

## Supersedes or superseded by

Implements the attachment half of ADR-0010 phase E6. Applies ADR-0012 to
attachment. Related: ADR-0005 (device as a learned identity anchor),
ADR-0013 (device facets).
