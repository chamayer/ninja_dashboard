# PLAN-048 — Source records report typed facts, not JSON parsed on read

**Status: ready.** Registered 2026-11-03 from the PLAN-012 follow-up on the
Source Records page. Defined, not started. Migrations, rehearsal, commits,
pushes and deployment keep their usual gates.

**Decision record:** [ADR-0055 — A source record's reported facts are derived
when it is written](../../operations/docs/decisions/0055-record-reported-facts-are-derived-at-write.md)
(Proposed). The ADR governs the design; this plan owns evidence, steps and
validation.

## Goal

Reading what a source record reports never parses its JSON. The Source Records
list returns its first page in well under a second, and every other reader of
`v_entity_observation_admin_metadata` gets the same benefit without code
changes.

## Evidence (production, read-only, 2026-11-03)

- First page of Source Records: 14.2 s before 0.143.0, about 8 s after its
  page-first query fix. The remaining cost is the view reading each record's
  JSON (1.1 GB TOAST, about 78,000 rows) for every row before the limit.
- Reading the JSON for all rows: 3.1 to 4.2 s with 18 separate extractions,
  3.5 to 4.3 s in one `jsonb_to_record` pass, 0.55 s for the table without the
  JSON. Extraction style does not matter; touching the JSON does.
- The restricted check reads the JSON in the join for every row, so even a
  keys-only query took 4.7 s. An ordered index is not used through the view
  (rehearsal with 50,000 rows).
- The view derives 15 columns from the JSON; claims map only 9 of the
  underlying fields (`archived`, `domain`, `hostname`, `hudu_layout`,
  `hudu_url`, `is_online`, `link_verdict`, `serial_number`, `vm_uuid`).
- Active claims by record state: withdrawn unlinked 0 of 3,427; withdrawn linked
  0 of 2,842; active unlinked 5,609 of 9,771; active linked 25,184 of 26,592.
  Claims cannot serve Source Records.
- The JSON has one writer (`ingest/observations.py` upsert; plus the
  `seed_observation_current` command).
- Readers and the columns they use: Source Records views (`canonical_hostname`,
  `canonical_serial`, `reported_last_contact_at`, `reported_name`,
  `reported_online`, `restricted`, `vm_uuid`); `views.py` (those plus
  `archived`, `hudu_company_id`, `link_verdict`, `platform_group_id`,
  `process_monitors`, `source_layout`, `source_url`); Issue review; client
  domains (`canonical_domain`); Computer naming (`canonical_hostname`,
  `reported_name`); `ingest/source_records.py` (`archived`, `link_verdict`,
  `platform_group_id`, `reported_last_contact_at`, `reported_online`,
  `restricted`, `vm_uuid`).

## Design (summary of ADR-0055; the ADR governs)

1. Typed, stored generated columns on `entity_observation_current` for the
   record's reported facts, computed by the database from its own data on every
   write.
2. The view reads those columns; contact-time parsing and the restricted flag
   stay at read time on short typed values (not immutable / live policy).
3. View columns, security barrier and readers unchanged; the JSON stays the raw
   evidence.
4. Fallback if the migration lock is too long: a one-to-one facts table filled
   by a trigger on the same table, with the same view change.

## Steps

| Step | Item | Gate |
| --- | --- | --- |
| 0 | Work in a separate git worktree and branch; the main checkout holds another session's in-progress work. Number the migration after PLAN-045's. | — |
| 1 | Measure the migration's lock: time a rewrite of `entity_observation_current` with the generated columns on a production-size copy, and the generated-column expressions over all rows read-only on production. Choose generated columns or the fallback; complete ADR-0055. | Rehearsal approval; user accepts ADR-0055 |
| 2 | Migration: generated columns (or facts table and trigger), view replaced with identical columns; reverse restores the 0348/PLAN-004 view. | Migration review |
| 3 | Tests: every column of the new view equals the old view for each record (equivalence query), including withdrawn, unlinked and restricted records; unit tests for the boolean and contact-time mappings. | — |
| 4 | Read-only production comparison of old and new expressions on all rows before release (zero differences, or each difference explained). | Read-only production approval |
| 5 | Release; measure Source Records and the Computer page reads after deploy (read-only). | Push approval including the migration |

## Validation and acceptance

- Zero differences between the old and new view on production data.
- Source Records first page under 1 s warm; no reader changes code.
- `EXPLAIN` of the view shows no access to `canonical_data` or `raw_data`.

## Risks

- Table rewrite and exclusive lock during the migration (measured in step 1);
  ingest and Jobs must not hold the table open across the deploy (startup
  migration lesson from 0.131.0).
- Expressions must stay immutable for generated columns; anything else moves to
  read time on typed columns.
- PLAN-047 may later separate narrow and wide observation data; this plan keeps
  the typed facts on the record so that change stays independent.

## Related

ADR-0055 (this plan's decision), ADR-0050 (record-level facts), ADR-0012
(claims), ADR-0053, ADR-0054; PLAN-012 (found it), PLAN-004 (reported contact),
PLAN-047 (write volume and storage).
