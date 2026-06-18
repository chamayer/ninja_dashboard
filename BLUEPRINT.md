# Goal

Switch agent-compliance customer identity from name-matching to stable
upstream id-matching, and clean up the duplicate clients that the
name-only path created when customers were renamed in their platforms.

# Why

When Ninja renames an org (same `platform_group_id`, new
`platform_group_name`), today's discovery treats the new name as an
unknown customer and mints a new `clients` row. Result on 2026-06-18:
client_ids 1299, 1300, 1301 were created as duplicates of existing
clients 22, 7, 10 (PCHC, City Painting via CPS, GF Supplies). Matrix
rows split, dashboards show both old and new entries, operators have
to pick which to trust.

The platforms (Ninja, S1, LMI, SC) all expose a stable per-customer id
that never changes on rename. We already store it as
`platform_observations.platform_group_id`. We just never used it for
identity. This change makes that id the canonical join key and treats
the display name as a refreshable label.

Aliases (`client_aliases`) stay only for cross-platform identity glue
(S1's group id ↔ Ninja's org id ↔ same customer). They are no longer a
rename-mitigation mechanism.

# Scope

- New table `client_platform_links` recording
  `(client_id, platform, platform_group_id)` mappings.
- One migration to create the table; one migration (or script) to
  backfill from existing observations and merge the 3 known duplicate
  client_id pairs.
- Ingest change: discovery looks up id-link first; falls back to
  name/alias matching only when no link row exists.
- On id-link match, `clients.client_name` auto-refreshes to the latest
  observed name from the platform (Ninja wins on tie).
- One-time cleanup of stale matrix rows and superseded
  `org_candidates` rows.

# Out of scope

- No changes to compliance evaluation, finding signatures, or matrix
  schemas.
- No changes to operator dashboards or filters - `client_id` is still
  the join key everywhere.
- No removal of `client_aliases` table or existing alias rows. They
  remain valid for cross-platform glue.
- No retroactive rewrite of `compliance_matrix_history` -
  historically accurate as-is.

# Decisions locked in

1. **Duplicate-pair winner:** keep the OLD client_ids (22, 7, 10).
   Demote new ids (1299, 1300, 1301) to `enabled=false, source='demoted'`.
   Reason: preserves run_log, snapshot, and alert continuity. Treat
   the rename event as if it never minted duplicates.
2. **Name refresh on every link match:** yes. Whenever the upstream
   platform's `platform_group_name` differs from
   `clients.client_name`, the canonical name updates to the
   latest-observed value. Ninja is authoritative when multiple
   platforms disagree.
3. **Backfill scope:** write link rows for every distinct
   `(platform, platform_group_id)` seen in `platform_observations`,
   including S1 / LMI / SC even where they did not create duplicate
   clients today.
4. **Simplicity over clever:** GoFlow/Goflow casing and similar
   normalize-collisions are not special-cased. Whatever Ninja last
   reported wins.

# Files to change

- `sql/migrations/052_client_platform_links.sql` - new table + PK +
  indexes.
- `sql/migrations/053_client_platform_links_backfill.sql` - backfill
  + 3-pair merge + matrix cleanup + candidate cleanup.
- `ingest/agent_compliance/config_loader.py` - discovery lookup
  order: id-link → alias-by-name → mint new client.
- `ingest/agent_compliance/ingest.py` - if the matrix builder or
  observation processor reads `clients.client_name`, ensure it picks
  up refreshed names.
- `CHANGELOG.md` - v0.32.0 entry.
- `VERSION` - bump to `0.32.0`.
- `SESSIONS.md` - session note.
- `TODO.md` - move "device aliases" idea to Permanently parked
  (superseded by id-link model); mark the rename cleanup as done.
- `HANDY_COMMANDS.md` - add a validation query to confirm link
  coverage and zero remaining duplicate (platform, group_id) →
  client_id pairs.

# Steps

1. Write migration 052 (table + PK + indexes).
2. Write migration 053:
   - INSERT INTO client_platform_links SELECT DISTINCT
     latest-name-per-pair → most-recently-assigned client_id, per
     `(platform, platform_group_id)`.
   - For the 3 known Ninja conflict pairs: pick the old client_id as
     winner, repoint compliance_matrix_current rows from
     loser → winner (DELETE losing rows where winner already has
     same norm_name), demote loser client.
   - UPDATE clients.client_name on winners to the current Ninja name.
   - Close superseded org_candidates rows.
3. Patch `config_loader.py` discovery:
   - Build an id-link cache at start of run.
   - On each observation with a `platform_group_id`: lookup link;
     match wins regardless of name.
   - On match with name drift: schedule a `clients.client_name`
     update (commit once per run, not per observation).
   - On no link: existing alias/name path; on success, write the new
     link row.
4. Bump `VERSION` to `0.32.0`. Update CHANGELOG.
5. Commit + push.
6. Wait for Portainer to redeploy.
7. Run `curl -fsS -X POST http://127.0.0.1:8090/run/agent-compliance`
   on am-ch-01.
8. Verify:
   - `SELECT platform, platform_group_id, COUNT(DISTINCT client_id)
      FROM platform_observations po JOIN client_platform_links USING
      (platform, platform_group_id) GROUP BY 1,2 HAVING COUNT(DISTINCT
      client_id) > 1;` returns 0 rows.
   - Client 22 (PCHC) has the new name `PCHC - Parent Care`.
   - Client 7 (City Painting) has the new name `City Painting`.
   - Client 10 (GF Supplies) has the new name `GF Supplies / Sigo Signs`.
   - Clients 1299, 1300, 1301 are disabled and have zero matrix rows.
   - Dashboard customer filter shows only the consolidated names.
9. Report the short commit hash in chat.

# Open questions

- Should the link row record the discovering `source_id` (FK to
  platform_sources)? Useful for SC where the same client may have
  multiple sources. Default in schema: nullable; PK uses
  COALESCE(source_id, 0). Confirm during implementation.
- Should we log every name refresh into a small audit table, or just
  let `clients.updated_at / updated_by` reflect it? Default: rely on
  `updated_by='id_link_refresh'` and updated_at; no audit table.

# Status

implemented - pending commit + Portainer redeploy + on-host
verification
