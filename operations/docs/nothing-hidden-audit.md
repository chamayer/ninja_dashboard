# "Nothing hidden or silently ignored" audit

**Purpose:** Systematic sweep of every silent filter, drop, or skip in
the ingest / evaluator / resolver code paths. Per the durable rule
(`memory/feedback_nothing_hidden.md`, 2026-07-20): "Any observation,
row, or attribute the code filters out or drops needs an
operator-visible surface (finding, view, or admin queue). No silent
exclusions."

**Method:** grep across `ingest/` for the common silent-filter
patterns (`if not ...: continue`, `if x is None: continue`,
placeholder / junk / filter comments, SQL `WHERE ... IS NOT NULL` and
`FILTER (WHERE ...)`), then classify each hit.

**Classification key:**

- **SURFACED** — filter still applies, but the affected set is
  operator-visible (Finding, admin table, or view).
- **INTENTIONAL — noise suppression** — deliberate signal-reduction
  filter with a documented rationale, not hiding actionable state.
- **GAP** — silent filter with no operator surface; violates the
  rule; needs a follow-up slice.

---

## SURFACED (already covered)

### `is_usable_serial()` filter → `placeholder_serial` + `shared_serial` findings (0.70.0)

- **Site:** `ingest/normalize.py::is_usable_serial()`; used at
  `ingest/identity/resolver.py:80,255,310,657,819` to gate identity
  matching.
- **Filter effect:** BIOS / template placeholder serials ("None",
  "Default string", "System Serial Number", "0000000", strings of
  length <4, all-same-character strings) never drive identity
  matches.
- **Surface:** `placeholder_serial` FindingType (0.70.0). Devices
  with junk serials surface as high-severity findings via the
  resolver's `_sync_device_attributes` sweep.

### Shared-serial silent grouping → `shared_serial` finding (0.70.0)

- **Site:** implicitly, the resolver's serial-based match code
  refuses to unify two devices with the same serial unless other
  signals corroborate. The affected set used to only surface on the
  retired `identity_candidates_list` admin page.
- **Surface:** `shared_serial` FindingType (0.70.0). One finding
  per (client, serial) with all sharers in `finding_details`.

### Unresolved observations → `unmatched_source_group` finding (0.70.0)

- **Site:** `ingest/source_observations.py` writes to
  `operations.unmatched_source_groups` when an observation can't
  match a device.
- **Surface:** `unmatched_source_group` FindingType (0.70.0). One
  finding per pending row via `_sync_device_attributes` sweep.

### Source-failure skip in the evaluator → `source_failure` admin finding

- **Site:** `ingest/evaluator.py::_source_failure_guard()`; used at
  `evaluator.py:655` to skip a platform's coverage evaluation when
  its latest run failed.
- **Filter effect:** coverage findings for platform X are suspended
  when platform X ingest is broken (so operators aren't spammed by
  false "missing agent" alerts when the real problem is a busted
  connector).
- **Surface:** `source_failure` admin Finding — the guard maintains
  it. See `_source_failure_guard()` docstring around
  `evaluator.py:121-184`.

### Placeholder org names / org excludes → admin-editable tables

- **Site:** `ingest/identity/client_resolver.py:108-112`. Silently
  skips groups whose normalized name matches either
  `operations.placeholder_org_names` or `operations.org_excludes`.
- **Filter effect:** the exclusion lists prevent auto-creation of
  client candidates for known noise names.
- **Surface:** both lists are admin-managed tables — operators
  add/remove entries via the standard admin UI. Skips reflect
  operator-authored policy, not silent hiding. **Note:** the entries
  themselves are visible; the individual observations they filter
  out are not enumerated back as "you told me to hide these
  N groups from source X." If that visibility matters, needs a
  follow-up. Currently classified as SURFACED via operator intent.

### Retired / deleted entities → intentional per ADR-0002

- **Site:** `WHERE deleted_at IS NULL` patterns across matviews +
  Django `.filter(deleted_at__isnull=True)` in views.
- **Filter effect:** retired devices and clients don't appear in
  active queries (they stay queryable, per ADR-0002).
- **Surface:** operator explicitly retired the entity. Retirement is
  auditable (`audit_log`). Not silent hiding.

---

## INTENTIONAL — noise suppression

### Per-agent stale suppressed when device is fully offline

- **Site:** `ingest/evaluator.py:706, 1073` (comments:
  "redundant noise for a device nobody can reach", "per-agent stale
  becomes noise").
- **Filter effect:** when the whole device is offline (all sources
  quiet), per-agent stale findings are suppressed in favor of a
  single `device_offline` finding.
- **Rationale:** reduces N-noise-per-offline-device that would
  otherwise fire; the higher-level `device_offline` finding is the
  operator-visible surface. Explicit design decision.
- **Verdict:** intentional, documented, and operator-visible via
  the aggregate finding. Not a gap.

### Snoozed / suppressed findings hidden from active queue

- **Site:** `findings_queue` view filters on
  `snoozed_until` and status.
- **Filter effect:** operator-snoozed or -suppressed findings don't
  clutter the active queue.
- **Verdict:** operator-authored action; opt-in reveal via `?snoozed=1`
  and `status=all`. Not silent hiding.

---

## GAP — silent filters that need a surface

### `_JUNK_MACS` filter — junk / placeholder MAC addresses

- **Site:** `ingest/normalize.py:85`. Filter set:
  `{"00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "02:00:4c:4f:4f:50"}`
  (all-zero, all-FF, VirtualBox default NAT MAC).
- **Filter effect:** junk MACs are never used as identity
  correlators. Devices reporting these MACs still get all their
  other identity signals, but the MAC itself is silently
  disregarded.
- **Why it's a gap:** analogous to `placeholder_serial`. Devices
  with a junk MAC don't produce a Finding today. Operators can't
  see "these N devices are reporting VirtualBox default MAC and
  are therefore not MAC-correlatable" without reading the source
  code.
- **Proposed fix:** `placeholder_mac` FindingType + emitter in the
  resolver's `_sync_device_attributes` sweep. Same pattern as
  `placeholder_serial`.

### Empty-name source groups silently dropped

- **Site:** `ingest/identity/client_resolver.py:104-106`. When a
  source group arrives with an empty `name` or empty
  `normalized_name` (e.g., LMI "-1" placeholder groups), it's
  silently skipped.
- **Filter effect:** the operator never learns that source X is
  publishing unnamed groups they can't route.
- **Why it's a gap:** these groups don't even become
  `unmatched_source_group` findings because they're skipped before
  that logic. Total invisibility.
- **Proposed fix:** `unnamed_source_group` FindingType (subject:
  source_binding). Emit at the skip site. Low-severity but visible.

### Individual observations filtered by `placeholder_org_names` / `org_excludes`

- **Site:** `client_resolver.py:108-112` (see SURFACED note above).
- **Concern:** the exclusion lists themselves are operator-visible,
  but the individual observations each entry causes to be dropped
  are not enumerated. If an org_excludes entry is applied to a
  source that later becomes legitimate, the operator has to
  proactively review and remove the entry — no signal that new
  observations are being caught by the filter.
- **Proposed fix (lower priority):** count per exclude entry — how
  many observations it dropped this drain. Surface on the admin
  table. Not urgent unless operators report surprise-filtering.

---

## Not audited in this pass

Deep-dive on evaluator noise-suppression rationale files (patch
finding suppression, coverage requirement threshold gates, etc.):
these have their own design docs and are known deliberate filters,
but a "does the rationale still hold" audit is a separate concern.

Matview WHERE clauses in `sql/migrations/` (ingest side) and
`operations/apps/core/migrations/` (matviews like
`device_agent_presence_current`, `device_session_current`,
`device_patching_scope_current`) — most filter out `entity_type =
'software'` or `deleted_at IS NOT NULL` which are intentional
scope-limiters, not silent hides. Skipped from this pass unless a
specific matview's filter turns out to hide operational state.

Ad-hoc `Untitled*.ps1` scripts and legacy scripts under
`script-dev/` — separately covered in
`legacy-scripts-parity-audit.md`.

---

## Aggregate

**Two clean gaps to close** (small, mechanical follow-ups; the
`_JUNK_MACS` one is the closest analog to what 0.70.0 already
built):

1. `placeholder_mac` FindingType + emitter (mirror of
   `placeholder_serial`).
2. `unnamed_source_group` FindingType + emitter at the empty-name
   skip site in `client_resolver.py`.

**One deferred concern:** per-exclude-entry drop counts — nice to
have, not urgent.

**Everything else:** either already surfaced (0.70.0 arc), or
intentional noise suppression with clear operator-visible
alternatives. The rule holds across the surveyed codebase.
