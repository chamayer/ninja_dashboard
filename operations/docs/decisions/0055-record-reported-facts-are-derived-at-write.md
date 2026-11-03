# 0055 — A source record's reported facts are derived when it is written

Status: Proposed
Date: 2026-11-03

## Context

`v_entity_observation_admin_metadata` (security barrier) is how six readers see
what a source record reports: Source Records, the Computer page, Issue review,
client domains, Computer naming and `ingest/source_records.py`. It derives 15
columns from the record's JSON on every read: hostname, reported name (hostname
or guest name), serial, VM UUID, domain, online state, reported contact time,
layout, URL, link verdict, archived, platform group, process monitors, Hudu
company id (from `raw_data`), and the restricted flag (layout against the live
`restricted_source_layouts` configuration).

Measured on production (read-only, 2026-11-03): the JSON is 1.1 GB of TOAST
for about 78,000 rows. Reading it for every row costs 3 to 4 s whether the
fields are extracted one by one or in one pass, and the restricted check reads
it in the join for every row even when no JSON column is selected. The Source
Records first page takes about 8 s; an ordered index is not used through the
view (rehearsal).

Attribute claims (ADR-0012) cannot replace the view. Only 9 of the 15 fields
are mapped to claims (not guest name, contact time, generic layout, platform
group, process monitors, company id), and claims exist only for active records
attributed to an entity: all 6,269 withdrawn records and 4,162 of the 9,771
active unlinked records have no active claims. Source Records lists exactly those
records. These are facts asserted by one source record, which ADR-0050 places
on the record.

## Options considered

- Index or query rewrite: does not help; the view must read the JSON per row.
- Read the fields from claims: blanks withdrawn and unattributed records and
  leaves six fields unmapped.
- A separate summary table maintained by a trigger: a second writer and a
  second copy that can drift, framed as a cache of the view.
- Typed record facts derived by the database from the record's own data when it
  is written, as generated columns of `entity_observation_current` (selected).

## Decision

Proposed (2026-11-03):

1. **A record's reported facts are typed columns derived from its canonical
   data at write time.** Each is a `GENERATED ALWAYS AS (...) STORED` column of
   `entity_observation_current`: hostname, guest name, serial, VM UUID, domain,
   online state (the view's boolean mapping), contact time as source text,
   layout (`source_layout`, else `hudu_layout`), URL, link verdict, archived,
   platform group, process monitors (JSON array) and Hudu company id. The
   database computes them in the same write, so there is no second writer and
   they cannot disagree with the JSON.
2. **Expressions that are not immutable stay at read time on the typed
   columns.** Parsing contact text into a timestamp (time-zone dependent) and
   the restricted flag (live configuration) are evaluated by the view on short
   typed values, not on the JSON.
3. **The view keeps its columns and security barrier** and reads the typed
   columns instead of the JSON. Its six readers do not change.
4. **The JSON remains the raw evidence**, read only where a page shows the raw
   record or an audit needs it. Attribute claims keep their own projection;
   moving the claim projector onto the typed facts is a separate decision.

## Rationale

The facts are a pure function of the record's data, so the database is the
right place to compute them, once per write, with consistency enforced by the
column definition rather than by code. Readers stop paying for the JSON on
every request. Restriction stays a live policy evaluated at read time, not a
copy stored on evidence (the same separation as ADR-0053 and ADR-0054).

## Consequences

- Required: one migration adding the generated columns and replacing the view;
  tests that each typed column equals the view's previous value for every
  record; a production comparison (read-only) before release.
- Risk to measure before acceptance: adding stored generated columns rewrites
  `entity_observation_current` under an exclusive lock (about 78,000 rows,
  1.57 GB heap plus 1.1 GB TOAST). The rewrite also removes the table's current
  bloat. If the measured lock is too long for a deploy, the fallback is a
  one-to-one record-facts table filled by a trigger on the same table, with
  the same view change.
- A new reported field needs a column definition in a migration, not reader
  code.
- Writes of a record compute the expressions; the cost is per write and small
  next to the JSON itself (PLAN-047 tracks write volume).

## Supersedes or superseded by

Refines the view introduced in migration 0348 and extended by PLAN-004
(reported contact). Related: ADR-0012, ADR-0050, ADR-0053, ADR-0054, PLAN-047,
PLAN-048.
