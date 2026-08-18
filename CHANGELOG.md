# Changelog

All notable changes to this project follow [Semantic Versioning](https://semver.org/).

## [0.119.9] — 2026-08-17 — Cross-client serial conflict drill-through

### Fixed

- Device-page cross-client serial findings now open the complete conflict group
  in Issues instead of a hidden one-device filter. The queue identifies the
  shared serial evidence and shows every affected device's finding.

### Changed

- Added a data-owned Finding Type drill-through key (migration 0143). Empty
  preserves device scope; `cross_client_serial` is seeded to group by `serial`.

## [0.119.7] — 2026-08-17 — Cross-client serial review

### Fixed

- Added per-device `cross_client_serial` findings for usable serial evidence
  reported under multiple clients. The finding is a review signal on every
  affected device; it never merges devices or changes coverage.
- Retained Ninja service tags as current serial evidence so a host record and
  an RMM record under different clients can be surfaced for review.

### Changed

- Moved explicit rejected serial values, including `Default string`, into the
  Operations-managed identity-value registry (migration 102). Missing serials
  remain silent; structural filler checks remain in code.

### Notes

- Migration 0141 registers the `cross_client_serial` finding type and the
  registry editor. The next Ninja collection and identity resolver sweep emit
  newly detectable conflicts.

## [0.119.6] — 2026-08-17 — Device patch-signal source guard

### Fixed

- Prevented device-detail pages from failing when an unrelated source link has
  a numeric identifier outside Ninja patch-signal's integer range. The patch
  context now reads only valid Ninja source-link IDs, preserving patch data for
  devices that have a valid Ninja link.

### Notes

- No migration or patching-policy change.

## [0.119.5] — 2026-08-17 — Product authorization scope context

### Changed

- Client-scoped product authorization choices on Software product detail now
  show each client's current device and installation counts. This supports
  informed authorization of ScreenConnect and every other recognized product
  without changing authorization precedence or creating any policy rows.

### Notes

- Counts come from the complete current-installation relation, not the
  page's capped device list. No migration or finding-emission change.

## [0.119.4] — 2026-08-17 — Capability gate configuration correction

### Fixed

- Removed the nonstandard Compose override for software-capability gates.
  Capability gate values again use only the existing mounted runtime `.env`
  configuration path.

## [0.119.8] — 2026-08-17 — Ninja device shadow views readable again

### Fixed

- Restored `/software/user-risk/`, which had returned HTTP 500 on every request
  since migration 0117. That migration revoked table `SELECT` on
  `entity_observation_current` to protect the restricted observation payload,
  but `ninja_device_detail_current_shadow` and
  `ninja_device_health_current_shadow` are `security_invoker`, so their
  permission check runs as the calling role and both stopped being readable.
  They are now `security_barrier` views owned by `operations_view_owner` —
  the pattern 0117 established for itself — so the application sees only the
  columns they project and the payload remains restricted.

### Notes

- Found by loading all 30 operator-facing pages synthetically. The failure took
  26 ms, so no timing-based check would ever have flagged it, and migration
  0122 had examined both views without noticing the missing privilege.
- `ninja_device_seen_daily_shadow` is deliberately left alone: it reads
  `source_record_seen_daily`, where `operations_app` has `SELECT` and
  `operations_view_owner` does not, so re-owning it would break a working view.
- Rehearsed against production in a rolled-back transaction. Tenant isolation
  still applies, and reads of `canonical_data` or of an unprojected key still
  fail with permission denied.

## [0.119.12] — 2026-08-18 — /software/user-risk/ under the worker timeout

### Fixed

- `/software/user-risk/` took ~123 s and would 500 behind a gunicorn worker
  timeout. Two defects, in the same query:
  - `device_user` joined a CTE to `v_device_source_link` on
    `external_id::integer = ninja_device_id`. PostgreSQL inlined the CTE into
    a Nested Loop run once per user (4,542 times measured), each iteration
    bitmap-scanning every link row for the Ninja source instance and applying
    the cast as a Join Filter rather than an index condition — 28.3 million
    rows removed by that filter. Forcing the link set to materialise once (`AS
    MATERIALIZED`) before hash-joining drops this from 86 s to 4.6 s.
  - `decision_items` matched `software_decisions` to installations with `OR
    (title match) OR (publisher match)`, and the planner could not use either
    side as an index condition: it built the full devices × decisions cross
    product (5,453 × 254 rows), then filtered the OR afterward, removing 44.8
    million rows. `software_decisions` has a XOR constraint guaranteeing
    canonical_name and publisher are never both set, so splitting into two
    `UNION ALL` branches — each a real equi-join — cannot double-count.
    38.9 s → 1.9 s for identical rows.
  - Combined: ~123 s → ~9 s (no client filter) / ~6 s (filtered).

### Notes

- Same family as the `/devices/` and `/software/decisions/` fixes: an
  expensive relation evaluated once per row instead of once per page.
- The publisher-match `OR` pattern also appears in
  `/software/tech-checklist/`'s decision query; not fixed here — recorded in
  the backlog since that page survives at 23.6 s cold / 1.9 s warm.
- Verified against production with and without a client filter; every row
  returned under a filter was correctly scoped to that client.

## [0.119.13] — 2026-08-18 — /software/tech-checklist/ decision query fixed

### Fixed

- `/software/tech-checklist/`'s decision-cleanup query (`decisions_sql`)
  matched `software_decisions` to installations with `OR (title match) OR
  (publisher match)`, the same defect already fixed in
  `/software/decisions/` (de046ee) and `/software/user-risk/` (c0b932a):
  neither side of the OR could be used as an index condition. Measured
  2026-08-18: 21–38 s, confirmed as the dominant cost of the page.
  `ck_software_decisions_scope_key_xor` guarantees `canonical_name` and
  `publisher` are never both set, so splitting into two `UNION ALL`
  branches — each a real equi-join — cannot double-count: 1.3–2.4 s for
  identical rows.
- Verified with a combined client-and-role filter against the exact assembled
  SQL: 42 correctly-scoped rows in 82 ms, confirming the doubled parameter
  list (`client_params * 2`, one set per UNION ALL branch) is correct.

### Notes

- An earlier backlog note attributed this page's slowness to `findings_sql`
  based on a truncated statement-shape key that had merged two different
  queries under one 60-character prefix. Re-measured directly: `findings_sql`
  alone is fast (under 1 s); `decisions_sql` was the actual cost. The note is
  removed now that the real cause is fixed.

## [0.119.14] — 2026-08-18 — Admin overview: one query instead of four

### Fixed

- `/admin/overview/` issued four separate round trips for its finding tile
  counts, one of them (`nav_pending_software_decisions`) a byte-for-byte
  duplicate of another (`software_findings_open`) — same tenant, same status
  filter, same category filter, queried twice. The three distinct counts are
  now one grouped aggregate (`Count(..., filter=...)`), and the duplicate
  reuses that result instead of re-querying. Verified identical results;
  measured 3,999 ms → 117 ms for the four round trips this replaces.

### Notes

- The other pages flagged as "slow" in the same measurement pass
  (`/findings/`, `/software/`, `/software/products/`, `/software/publishers/`,
  `/patching/activity/`) were re-measured in isolation and found to vary with
  concurrent host load (load average observed between ~4 and ~8 during this
  session), not with a fixable defect in the query itself — the same query
  ran 14-20 s under load and under 700 ms moments later with no code change.
  Nothing further was changed there.

## [0.119.2] — 2026-08-17 — Capability permission checks

### Fixed

- Corrected the app label in the software capability and authorization
  permission checks. Both named `core.`, while the app is registered as
  `operations`, and `has_perm` matches the label exactly — so neither check
  could ever pass. Superusers short-circuit that check, so the controls worked
  for them while silently never rendering for anyone else, and granting the
  permission in the admin did not help because the string being checked did not
  name it. Capability curation was affected since it shipped; product
  authorization since 0.118.0.

### Changed

- Centralized the authorization permission as
  `capability.AUTHORIZE_PERMISSION`, replacing two literal copies in
  `views.py`. Having one definition per call site is how the label drifted in
  the first place.

### Notes

- No migration. The `auth_permission` rows were always correct; only the
  strings checking them were wrong.
- Added `test_permission_strings`, which resolves each permission against the
  app registry rather than asserting a check is merely present. Verified to
  fail when the original defect is reintroduced.

## [0.119.1] — 2026-08-14 — Intel matcher lookup index

### Fixed

- Indexed `intel.cves.affected_cpes` (migration 101). The intel matcher ran for
  41 minutes, four times a day, because its per-title CVE lookup
  (`affected_cpes ?| candidates`) had no GIN index and sequentially scanned all
  97,520 CVE rows on every call: 684 ms and roughly 143 MB of buffers per
  lookup, against 0.063 ms and 7 buffers with the index.

### Notes

- Full rebuild semantics are unchanged. Every run still deletes and reinserts
  the tenant's matches, which is what guarantees no stale match survives a CVE
  withdrawal; the deferred incremental-versus-full-rebuild question is answered
  by fixing the lookup rather than by trading that guarantee for speed.
- Measured: 34 MB index against a 137 MB table, 11.4 CPEs per CVE, 3.4 s to
  build. `jsonb_ops` is required because `jsonb_path_ops` does not support the
  `?|` operator. The build holds a brief exclusive lock during startup, before
  the service reports ready.

## [0.119.0] — 2026-08-14 — Endpoint security recognition

### Added

- Added 18 vetted endpoint-security rules (migration 100), covering
  SentinelOne, CrowdStrike, Symantec, Kaspersky, Trend Micro, Malwarebytes,
  ThreatDown, Huntress, Webroot, Avast, AVG and Panda. `endpoint_security`
  previously had 65 candidate products and no alertable ones, so
  `unauthorized_av` could not fire at all and recall was not claimable. It now
  recognizes 36 products across 4,233 devices and 73 clients.
- Recorded, in the migration, every candidate deliberately not promoted —
  browser extensions, password managers, VPNs, updaters, management agents and
  on-demand scanners from the same security vendors — so the omissions are
  decisions rather than oversights.

### Notes

- Each pattern was dry-run against the whole product catalog before being
  seeded, with no false positive in the result. Two traps shaped the patterns:
  `sentinel agent%` rather than `sentinel%`, because SafeNet and Thales ship
  software-licensing components sharing the first word; and
  `malwarebytes version%` rather than `malwarebytes%`, because Malwarebytes
  Privacy is a VPN.
- No finding behavior changes on deployment. Both capability gates remain off,
  and no authorization rows are created.

## [0.118.0] — 2026-08-14 — Software authorization, separate from coverage

### Added

- Added `operations.product_authorizations` (migrations 099 and 0139), which
  records whether a product may carry a capability at a client. Until now the
  classifier derived permission from coverage requirements, so the only way to
  authorize software was to mandate it: the MSP's own ScreenConnect instance
  read as unauthorized on 3,007 devices across 70 clients, and silencing it by
  making ScreenConnect required would have demanded it from the five clients
  that do not run it. Coverage requirements are unchanged and still state only
  what a client must run.
- Added an authorization control to the product detail page and a matching
  admin surface, both behind a new `authorize_software_product` permission that
  is separate from capability curation. Authorizations may be global or scoped
  to one client, must state permit or deny explicitly, and require a rationale.
- Recorded the reasoning in ADR-0019.

### Changed

- Unauthorized capability findings now resolve through a documented precedence
  ladder — client deny, client permit, global deny, global permit, then the
  required-platform mapping — and record which rule decided them. Deny precedes
  permit at each tier, so a client can be excluded from something permitted
  fleet-wide.
- An authorization is retired by withdrawal with a recorded reason rather than
  deleted, and re-authorizing inserts a new row so the gap stays visible.

### Notes

- No authorization rows are created by this release. Both capability gates
  remain off, so the new precedence ladder is not reached and no finding
  behavior changes on deployment.

## [0.117.0] — 2026-08-13 — Classifier-only job and mapping ratchet repair

### Added

- Added a "Software classifier (no intel refresh)" job, which runs the same
  path the scheduler uses. The existing classifier job first refreshes intel,
  including a title-to-CVE matcher pass measured at 41 minutes; the new entry
  re-emits software findings from the intel already stored.
- Job catalog entries may now set `run_all: false` to be held out of "run all".

### Fixed

- Stopped "run all evaluators" from starting two concurrent software classifier
  passes over the same findings. Nothing serializes them, so the new
  classifier-only job is excluded from bulk dispatch rather than being filed
  under a category it does not belong to.

### Changed

- Restored the hardcoded-domain-mapping ratchet to passing. Six module-level
  constants were reviewed individually: four finding-type, severity and display
  mappings are recorded as awaiting a data table, and the two capability
  constants are exempt — one is a write-ownership boundary that must stay in
  code so a row edit cannot widen a withdrawal onto evidence the projector
  cannot rebuild, and the other is a fail-closed schema probe.

## [0.116.3] — 2026-08-13 — Software detail legacy-evidence repair

### Fixed

- Made the Product detail page tolerate a legacy text-form safety-signal
  payload. Invalid legacy category evidence is ignored instead of causing an
  internal server error; valid JSON evidence retains its existing tag behavior.

## [0.116.2] — 2026-08-13 — Products page timeout repair

### Fixed

- Restored `/software/products/`. Its whitelist-suggestion title counter had
  timed out inside PostgreSQL and caused Gunicorn to return HTTP 500. The
  counter now resolves the finding-type registry id first and uses the existing
  partial expression index directly; the equivalent production aggregate
  completes in 57 ms.
- Made Products and Publishers decision controls scope-consistent. Their detail
  pages now support global, client, and device decisions; compact list actions
  remain global and link to the scoped form. Invalid narrow-scope submissions
  are rejected instead of being silently recorded globally.

## [0.116.1] — 2026-08-12 — Capability migration startup repair

### Fixed

- Synchronized the `finding_types` identity sequence before registering the
  capability review finding. This repairs an existing production sequence
  drift that prevented Operations migration 0137 from starting; the failed
  migration transaction made no partial schema or data change.

## [0.116.0] — 2026-08-12 — Reliable software capability recognition

### Added

- Added a global, evidence-backed capability model for endpoint security,
  RMM, and remote access software. Machine evidence records its source and
  confidence; an effective relation gives curator rejections and confirmations
  explicit precedence over vetted and candidate sources.
- Added exact product-identity mappings from required platforms to their
  agent, tray, updater, uninstall, and component products. This replaces the
  unsafe display-name containment used to sanction software.
- Added Operations capability evidence on software detail pages, curator-only
  confirm/reject actions with audit records, and an admin editor for platform
  product mappings.
- Added local capability projection, a manually runnable capability job, and
  the LOLRMM corpus connector. LOLRMM is alertable only for one-to-one exact
  normalized local product-name matches; collisions remain review candidates.

### Changed

- Approval decisions now suppress only finding types explicitly marked as
  trust-sensitive. They no longer silence vulnerability, malicious-intel,
  end-of-life, or suspicious-install-path facts.
- Retired PublisherCategory as a competing capability source. Its narrowly
  relevant AV/EDR, RMM, and remote-access patterns are seeded as candidate
  publisher rules instead.
- `multi_av_conflict` is disabled by default because installed-package
  inventory cannot prove concurrent active protection.

### Safety

- Capability enforcement and candidate-review emission default to off while
  production product mappings and shadow-mode precision/recall results are
  reviewed. Existing unauthorized findings are retained during that gate;
  the system never falls back to name-containment matching.

## [0.115.1] — 2026-08-12 — Issues scope is measurable at a glance

### Changed

- The Issues page's filtered scope cards now show both the count and a
  labeled fraction/percentage. Findings, actionable findings, and software
  policy candidates are compared with the selected status/snooze population;
  affected devices and clients are compared with the current fleet population.
  This makes the magnitude of a filter immediately visible without implying
  every card is a fleet-wide total.

## [0.115.0] — 2026-08-06 — Software page: 3.2s to ~1.1s

### Fixed

- **The software pages took over three seconds.** Measured end-to-end while
  logged in: `/software/` 3.19 s and `/software/products/` 3.54 s, both driven
  by the shared `_software_page_data`. Per-query profiling showed 3,524 ms of a
  3,954 ms render was SQL, concentrated in three queries.
- **Decision tile counts: 1,484 ms to 83 ms.** Three
  `COUNT(DISTINCT ...) FILTER (WHERE EXISTS (...))` clauses re-scanned
  `software_decisions` once per title — 20,631 titles times three. Now
  pre-aggregates decisions by name and by publisher, then hash-joins. Verified
  against production to return identical numbers.
- **New-in-24-hours panel: 718 ms to 0.18 ms.** It filtered
  `first_observed_at` with no index on that column, scanning all 481,365
  installation rows. Migration 0126 adds
  `(tenant_id, first_observed_at DESC) WHERE deleted_at IS NULL`.
- **Whitelist-suggestion tile: 1,015 ms to ~273 ms.** It counts distinct
  titles across 131,073 findings. Migration 0126 adds an expression index on
  the JSON key so the scan reads the index rather than the heap. It cannot go
  lower — PostgreSQL has no index skip-scan for `DISTINCT`, so all 131,073
  entries are read either way.

### Changed

- Corrected a stale comment claiming `v_software_safety` "costs ~700-900 ms per
  evaluation". It has since been materialized and the full unbounded fetch
  measures 19 ms. Fetching it once is still right, but it is not the page's
  cost center — the comment would have sent the next reader after the wrong
  thing, as it did this one.

### Note

- Both indexes are created `CONCURRENTLY`, so migration 0126 is non-atomic:
  `findings` and `software_installations_current` take continuous ingest
  writes and a plain `CREATE INDEX` would block them.

## [0.114.1] — 2026-08-06 — Every identity conflict now has an action

### Fixed

- **15 of 19 open `identity_conflict` findings had no action.** The findings
  queue only offered a merge link when the collision held exactly two devices,
  because `device_merge` takes exactly two device IDs. Production collisions
  run to 3, 4 and 5 devices — and the merge queue holds proposals of up to 10 —
  so most findings named a problem and offered nothing to click. Findings now
  link to the merge review queue, which handles any number of members; the
  direct two-device merge remains as a shortcut where it applies.
- The merge queue accepts a `key` filter so a finding links to its own
  proposal. The finding's `condition_key` and the candidate's `canonical_key`
  are the same string by construction, so the notification and the decision
  address one collision. The filter is shown on the page with a "Show all"
  escape and preserved when the other filters change, rather than silently
  narrowing the view.
- Merge queue CSV export listed `Created`, `Resolved` and `Resolved by`, none
  of which are fields on the model. `csv_export._resolve` defaults missing
  attributes to `""`, so they did not raise — they emitted three permanently
  blank columns, invisible while the queue was empty. Replaced with member
  count and match reason.
- Corrected the queue's description, which read "workflow lands with M2+ once
  multi-source ingest exists". Multi-source ingest landed long ago; the queue
  was empty because nothing produced rows.

## [0.114.0] — 2026-08-06 — Merge proposals are produced

### Added

- **`operations.merge_candidates` finally has a producer.** The review surface
  was fully built — queue page, navigation entry, admin tab badge, admin
  overview metric, client-directory column and Django admin — but nothing ever
  wrote a row, so all of it was permanently empty.
  `resolver._maybe_create_candidate` now writes the proposal alongside the
  `identity_conflict` finding it already emitted, carrying member snapshots,
  match reason and confidence. The finding remains the notification that a
  collision exists; the candidate is the reviewable decision.
- Migration 0125 adds a partial unique index on
  `(tenant_id, canonical_key) WHERE status = 'open'`, so repeat detections of
  the same hostname collision refresh one proposal rather than accumulating
  duplicates. `canonical_key` matches the finding's `condition_key`, so both
  surfaces address the same collision.
- Production of proposals is a **reconciling pass**, `project_merge_candidates`,
  running each resolver cycle — not a side effect of observation resolution.
  The first attempt hooked it to `_maybe_create_candidate`, which only runs
  while resolving an observation that has no device yet. Production has **zero**
  such observations and nineteen open `identity_conflict` findings, so that
  version would have left the queue permanently empty while real collisions
  existed. A collision is a property of current device state, so it is
  projected from that. Proposals whose collision no longer holds — after a
  merge, rename or deletion — are closed, so the queue reflects what is true
  now.
- Measured against production: 38 proposals across 8 clients, a second pass
  changes nothing, and the largest collisions carry 4 to 6 member devices.

## [0.113.0] — 2026-08-06 — Client renames become actionable

### Added

- **"Apply source name" action on `client_name_conflict` findings.** Track C
  replaced the old `bootstrap_clients_from_ninja` auto-rename with the rule
  "name drift = finding, never re-match", so an operator decides rather than a
  source silently overwriting canonical state. The finding half was built; the
  apply half never was, which left renames visible but unactionable — and with
  the bootstrap command retired in 0.112.0, unhandled entirely. The action
  sets `clients.display_name` to the observed source name, writes a
  `client.rename_from_source` audit row, and resolves the finding.
  `slug` is deliberately untouched: it appears in operator-facing URLs, and
  the retired bootstrap preserved it for the same reason.

### Fixed

- **The pending-merges badge could never show a count.**
  `context_processors` filtered `MergeCandidate` on `status="pending"`, which
  is not a member of `MergeCandidate.Status` (`open | merged | split |
  rejected`). Corrected to `Status.OPEN`. The queue still has no producer —
  tracked in `.work/backlog.md` — but the badge is no longer wrong on top of
  that.

## [0.112.1] — 2026-08-06 — Drop two superseded legacy materialized views

### Removed

- `operations.device_agent_presence_current_legacy` (0 rows) and
  `operations.source_health_current_legacy` (4 rows, superseded by
  `source_health_current`'s 5). Neither is referenced by any Python, template,
  shell or SQL outside frozen historical migrations, nor by any database
  function; the refresh coordinator drives only the current pair. Migration
  0124 drops them in dependency order behind a guard that fails on any
  unexpected dependent rather than using CASCADE.

### Note

- The three `ninja_device_*_shadow` views were previously recorded as empty
  and slated for retirement. They are not empty — they hold 5,499, 5,499 and
  357,669 rows and present `entity_observation_current` under legacy Ninja
  names so readers survived the snapshot cutover. The earlier figure came from
  joining `pg_stat_user_tables`, whose `n_live_tup` covers tables only and
  reports 0 for every view. They are working correctly and retiring them is a
  reader cutover, not cleanup.

## [0.112.0] — 2026-08-06 — Retire client_links; name drift becomes visible

### Fixed

- **`client_name_conflict` was suppressed down to a single finding.** The
  detector skipped the finding when the observed source name matched *either*
  the canonical client name or the stored `client_links.external_name` — while
  `client_resolver._attach_group` refreshed that column to the observed name on
  every sync, so the second test largely compared the observed value against
  itself. Measured after deployment: **1** open finding existed beforehand,
  dating from 2026-07-13, and **50** appeared on the first run afterwards, for
  51 open. Same defect class as the Ninja-only filter behind the `device_links`
  retirement in 0.111.0.
  Correction: the 0.112.0 commit message and an earlier draft of this entry
  said the detector "had never fired and could not". That was wrong — these
  findings are written to `operations.admin_findings`, not
  `operations.findings`, and the comparison uses `_norm()` rather than plain
  lowercase. Measuring the wrong table and the wrong comparison both pointed
  the same way. The change and its effect are unaffected; the description of
  the defect was overstated.

### Changed

- **`operations.client_links` is retired (migration 0123)**, replaced by
  `operations.v_client_source_link` over `entity_source_links`, maintained
  from observation evidence for every source. This is the client-side twin of
  the `device_links` retirement and completes the attachment half of E6. Four
  writers are removed; all readers move in this release with no compatibility
  alias. Verified against production: 320 rows both sides and **zero** source
  identities changing which client they attach to.
- `ClientLink` becomes the unmanaged, read-only `ClientSourceLink`; its admin
  surfaces are read-only and the view rejects writes.
- Attachment now follows evidence. The retired table pinned `client_id` on
  first write and never reassigned it, so a source group that genuinely moved
  between clients stayed with the original.

### Removed

- **`bootstrap_clients_from_ninja`** and its `entrypoint.sh` step. BLUEPRINT
  Track C superseded it on 2026-07-13 — no source is a client authority — and
  scheduled its removal as C.7, which never happened. It was a measured no-op
  (`created=0 updated=0 unchanged=75 total=75`) but would have auto-minted a
  client for any new Ninja org, which Track C forbids.
- `client_links.external_name`. It existed to suppress `client_name_conflict`
  and, being rewritten each sync, suppressed every drift instead. The
  attribute contract cannot reproduce it — `claim(name)` is per
  (client, source_instance) while `external_name` is per
  (source, external_id). An explicit operator-recorded "accepted name" remains
  a reasonable future feature.

## [0.111.1] — 2026-08-06 — Read models grant SELECT only

### Fixed

- **A view granted the application write access to two tables it was denied.**
  `ALTER DEFAULT PRIVILEGES` gives `operations_app` full DML on everything
  `operations_migrate` creates, and PostgreSQL's default-privilege object type
  `r` does not distinguish views from tables, so all 17 views and materialized
  views in `operations` inherited `INSERT`/`UPDATE`/`DELETE` regardless of what
  their migration granted. Most were inert — a materialized view accepts no
  DML, and a view is only auto-updatable from a single un-aggregated base
  table. Three were auto-updatable, and one was a real escalation: as
  `operations_app`, `entity_attribute_claim_current` and
  `entity_attribute_claim_history` are denied directly, as migrations 0115 and
  0117 intended, but `DELETE` through `v_entity_attribute_claim_storage_status`
  succeeded, because that view is `security_barrier` rather than
  `security_invoker` and so executes DML as its superuser owner. Migration 0122
  revokes `INSERT, UPDATE, DELETE, TRUNCATE` from the four runtime roles on
  every read model and asserts none remains. `SELECT` is unchanged, and no
  application code wrote through any of them.

### Changed

- `operations/AGENTS.md` now requires a migration creating a read model to
  revoke the DML it inherits. The default privilege cannot be narrowed to
  exclude views, so this rule and migration 0122's assertion are the
  enforcement; a continuous check is recorded in `.work/backlog.md`.

## [0.111.0] — 2026-08-06 — Retire device_links; source links follow observations

### Fixed

- **Agent presence was wrong for three of four sources.**
  `_sync_operations_device_links` maintained `device_links.last_seen_at` and
  `missing_since` under a `WHERE s.name = 'Ninja'` filter, so those columns
  were only ever kept current for Ninja. Measured against production: 209
  links reported an agent present that had stopped reporting 6-23 days earlier
  (SentinelOne 137, LogMeIn 65, ScreenConnect 7, Ninja 0), and `last_seen_at`
  was frozen far more widely — 3,026/3,031 LogMeIn, 1,013/1,013 ScreenConnect
  and 4,346/4,351 SentinelOne links disagreed with the observation-derived
  value, against 0/5,884 Ninja. 8,316 links claimed present with `last_seen_at`
  at least three days stale. `device_missing_from_source` resolves from
  `missing_since`, so that finding could not resolve correctly outside Ninja.
  After the cutover, stale-but-live links are 0 across all four sources.

### Changed

- **`operations.device_links` is retired (migration 0121)**, replaced by
  `operations.v_device_source_link` over `entity_source_links`, which
  `sync_entity_source_links_from_observations()` maintains from observation
  evidence for every source. This closes the last "competing attachment
  authority" named by E6: six code paths wrote the table directly, and all six
  are removed. Attachment is now derived from evidence, per ADR-0012.
- All readers move to the new relation in this release; no compatibility alias
  is left behind. The `DeviceLink` model becomes the unmanaged, read-only
  `DeviceSourceLink`, and its admin surfaces are read-only. `operations_app`
  holds SELECT only, so the write path is closed by privilege.
- Device merge no longer repoints source links directly. It moves the
  observations, and the links follow on the next sync with their history
  intervals correctly closed — writing the derived table directly would have
  orphaned the open `entity_source_link_history` row.

### Removed

- `match_method`, `match_confidence` and `external_name` as maintained by the
  identity writers. The first two are now the `entity_source_links` values;
  `external_name` was write-only and is dropped. No reader consumed any of
  them.

## [0.110.1] — 2026-08-05 — Fix run-log reaper integer overflow

### Fixed

- `runlog._reap()` computed `duration_ms` from wall-clock elapsed, which
  overflowed the `integer` column for long-orphaned rows — the oldest stuck
  run dated from 2026-06-03 and computed to ~5.4e9 ms against an int4 ceiling
  of 2.1e9. `reap_orphaned()` runs at ingest startup, so this crash-looped the
  ingest container in 0.110.0 and stopped all collection. Reaped rows now
  record `duration_ms = NULL`, which is also the truthful value: the process
  was killed, so elapsed wall-clock is not the run's duration.

## [0.110.0] — 2026-08-05 — Activities filter repair and platform-health findings

### Fixed

- **Activities ingest was collecting unfiltered since 0.7.1 (2026-06-03).** The
  `/v2/activities` query parameter is `status`, not `statusCode` — `statusCode`
  is not a recognized parameter and was silently dropped, so every call returned
  the full stream. Because 0.7.1 also removed client-side rejection, the
  configured `INGEST_ACTIVITY_TYPES_INCLUDE` allowlist has been inert for two
  months: 163 activity types were arriving against an allowlist of 16.
  Verified against the live API — `status=SYSTEM_REBOOTED` now returns only
  that code, while `statusCode=SYSTEM_REBOOTED` is indistinguishable from no
  filter at all.
- **Activities ingest had been failing hourly since 2026-08-04 16:34.**
  `capture_ninja_events()` issued `SET LOCAL operations.tenant_id = %s`;
  psycopg binds server-side, so Postgres received `$1` and raised
  `syntax error at or near "$1"`. The whole insert transaction rolled back, no
  rows were stored, and the cursor never advanced — meaning `NODE_DELETED`
  source events were also not captured. Now uses `set_config()`. Same fix in
  `ingest/relationships.py`. The identical pattern in `operations/` is correct
  and untouched: Django's backend binds client-side.

### Changed

- `SOFTWARE_ADDED` / `SOFTWARE_REMOVED` / `SOFTWARE_UPDATED` activities are now
  collected as inventory-rescan triggers but no longer stored. The durable
  record is `software_installations_current` plus its SCD-2 history; storing the
  event as well was ~1M rows of duplication. The per-run discard count is
  logged as `trigger_only_discarded`.
- `.env.example` records the `status`/`statusCode` parameter asymmetry, that an
  unrecognized code returns HTTP 500 and aborts the run while a valid but
  never-emitted code correctly returns zero rows, and that some codes match
  loosely rather than exactly.

### Added

- **Platform-health findings** (`ingest/platform_findings.py`). `source_failure`
  and `software_queue_stalled` were registered as `finding_class='admin'` types
  but nothing ever emitted them, while `activities` had failed 20 times in 7
  days, `agent_compliance` 11 times, and `software.activity` sat at four times
  its registered `max_depth`. Both now evaluate every 30 minutes and appear on
  the existing Operations admin health page without UI changes. A registered
  queue whose table cannot be measured is logged, not skipped silently.
- **Orphaned run reaping** (`ingest/runlog.py`). A killed process — SIGKILL,
  OOM, container stop — left its `run_log` row at `running` permanently; 96 had
  accumulated since 2026-06-03. `reap_orphaned()` runs at startup, where
  nothing from a previous process can still be running; `reap_stale()` runs
  every 30 minutes for hangs where the process lives but the work does not.
  Both record a distinguishable reason so a restart is not mistaken for a fault.

## [0.109.0] — 2026-08-04 — Audited restricted evidence reveal

### Added

- Added a default-denied restricted-evidence permission and POST-only reveal
  actions for current source payloads and redacted claim/effective values.
- Added database-enforced active-user, tenant, and permission checks; every
  successful reveal appends metadata-only context to the existing operator
  audit log before returning the protected value.

### Security

- Device identity GET requests no longer load raw observation payloads.
- Removed runtime direct reads of observation payload columns and the protected
  effective/conflict projection tables; named readers now use tenant-filtered,
  redacted or metadata-only views. Revealed responses are marked private and
  non-cacheable and remain excluded from CSV exports.

## [0.108.0] — 2026-08-04 — Generic entity administration

### Added

- Added tenant-filtered, registry-driven read models and Operations Admin
  surfaces for canonical entities, source identities, redacted claims and
  effective values, conflicts, relationships, and generic candidates.
- Added generic candidate attach/reject workflows through the existing atomic
  source-link, history, candidate-event, and audit services.
- Replaced fixed source class counts on the Sources page with source-instance
  rows and per-entity-type active/withdrawn counts.

### Security

- New generic read views are security-barrier views owned by a no-login,
  non-BYPASSRLS view role and exclude raw payloads and protected source-event
  actor data. Audited restricted/raw reveal and remaining direct-table grant
  removal stay in the next E5 slice.

## [0.107.3] — 2026-08-04 — E4 runtime privilege correction

### Fixed

- Explicitly revoked schema-default runtime grants before applying the E4
  least-privilege matrix. Raw relationship evidence/history and protected
  source-event payload/actor data are now ingest-only; Operations reads only
  registries, decisions, and effective relationship projections.

## [0.107.2] — 2026-08-04 — Candidate projector defaults fix

### Fixed

- Supplied the database-required empty decision metadata when the generic
  projector creates a candidate, and replaced the deployed projector through
  migration 0114. The failed first projection transaction inserted no rows.

## [0.107.1] — 2026-08-04 — Relationship migration startup fix

### Fixed

- Forced the relationship-type seed's deferred entity-class constraints before
  later ownership DDL, preventing Operations restart loops while applying
  migration 0111.

## [0.107.0] — 2026-08-04 — Generic relationships, candidates, and source events

### Added

- Added tenant-safe relationship type and authority registries, unresolved
  source evidence with change/presence history, audited include/exclude
  decisions, a changed-edge queue, deterministic effective edges, and
  supporting-evidence references.
- Activated the generic candidate/current-event projector over unattached
  stable source identities, including material-change reopen and authoritative
  source-link attachment handling.
- Added immutable generic source-event storage with protected actor metadata
  and exact-identity deletion-withdrawal confirmation.

### Changed

- Ninja activity collection now always requests `NODE_DELETED` and writes new
  immutable activities through the generic source-event contract alongside the
  temporary legacy activity compatibility write.

### Safety note

- Current measured Ninja deletion events contain an actor ID but no stable
  device ID. They are retained as unresolved evidence; message or hostname text
  is never guessed into identity, and no source or canonical record is deleted.
  Historical generic-event backfill remains a separate operational action.

## [0.106.1] — 2026-08-04 — Effective migration startup fix

### Fixed

- Forced the initial dirty-key backfill's deferred tenant constraints before
  later table-ownership DDL, preventing Operations restart loops while applying
  migration 0108.

## [0.106.0] — 2026-08-04 — Generic effective attribute engine

### Added

- Added tenant-safe typed operator decisions for single replace/clear and set
  replace/add/remove semantics, with database-enforced validation and atomic
  redacted audit events in the existing generic audit log.
- Added deterministic effective current values, set members, supporting-claim
  references, and visible equal-authority conflict state using explicit
  authority, conflict, and merge policies.
- Added a redacted tenant-scoped effective-value read model and read-only
  Operations admin inspection.

### Changed

- Claim changes and operator decisions now enqueue only affected
  entity/attribute keys. The bounded effective projector drains that durable
  queue instead of rescanning all claims at every collection boundary.

### Operational note

- Effective values remain an additive shadow projection. Existing typed
  consumers stay authoritative until E5 parity and cutover; this release does
  not add the decision workflow UI or alter existing reader contracts.

## [0.105.4] — 2026-08-04 — Fast claim no-op detection

### Fixed

- Reused the generic source record's stored material hash and version metadata
  for claim projection change detection, avoiding full JSON re-hashing across
  every source record at each collection boundary.

## [0.105.3] — 2026-08-04 — Built-in attribute hashing

### Fixed

- Replaced the unavailable `pgcrypto.digest` dependency with PostgreSQL 16's
  built-in `pg_catalog.sha256(bytea)` for claim and projection fingerprints.

## [0.105.2] — 2026-08-04 — Attribute-projector digest fix

### Fixed

- Qualified `pgcrypto.digest` calls in the security-definer claim projector so
  its deliberately restricted search path can resolve hashing functions.

## [0.105.1] — 2026-08-04 — Attribute-claim migration startup fix

### Fixed

- Forced deferred tenant-constraint checks after authority-policy seeding and
  before table-level RLS/ownership DDL, preventing Operations restart loops
  while applying migration 0103.

## [0.105.0] — 2026-08-04 — Generic attribute delta claims

### Added

- Added deployment-controlled attribute definitions, source-field mappings,
  independent identity and attribute authority policies, and tenant-safe typed
  current claims with SCD-2 change history.
- Added bounded, resumable claim projection from generic source records,
  aggregate withheld/unmapped-field counts, redacted claim evidence, and
  read-only Operations admin inspection.
- Added guarded 90-day closed-claim-history retention and an aggregate storage
  signal that calls for partition review at 10 million retained rows or 25,000
  changed members per day.

### Changed

- Collection boundaries now project attribute claims after source-link sync in
  separately committed batches. Heartbeat/contact timestamps remain on source
  current records and do not create claim writes.

### Operational note

- Claims remain an additive shadow path in this release; existing typed readers
  stay authoritative until effective-value selection and measured reader
  cutover. Unmapped raw fields default to restricted/count-only handling.

## [0.104.0] — 2026-08-03 — Generic entity and source-link kernel

### Added

- Added deployment-controlled entity-class/scope registries and thin generic
  entity anchors for canonical Clients and Devices without changing their
  existing IDs or typed authority.
- Added tenant-safe generic source-link current/history storage keyed by the
  complete stable source identity, plus generic candidate current/event
  foundations and read-only Django admin inspection.
- Added an idempotent shadow projector that anchors new typed records and
  synchronizes already-resolved generic observations after collection.

### Changed

- Expanded entity-type classification with independent entity class, license,
  requirement, identity, and lifecycle capabilities. License authority remains
  deny-by-default in this expansion phase.

### Operational note

- Migration 0101 backfills only exact existing Client/Device resolutions and
  leaves unresolved evidence unattached. Existing typed and compatibility
  links remain authoritative until measured parity and a later cutover.

## [0.103.0] — 2026-08-03 — Generic Ninja reader cutover

### Changed

- Made generic Ninja device-detail and device-health observations the
  authoritative current/raw storage path and stopped new hourly writes to the
  two legacy raw snapshot tables.
- Repointed current device, health, session, presence, last-user, patching, and
  daily active-device consumers to generic current evidence and compact daily
  rollups while retaining compatibility relation names.
- Added a compact Software title read model so the Operations overview no
  longer groups the full installation-current table on every request.

### Fixed

- Added a cross-process database single-flight guard around the complete patch
  cycle and dependency-ordered Software read-model refresh once per completed
  inventory batch.

### Operational note

- This release retains all legacy Ninja snapshot rows and tables for rollback.
  Archival, deletion, and disk reclamation remain a separately approved phase;
  Agent Compliance remains unchanged.

## [0.102.0] — 2026-08-03 — Inventory Metabase retirement

### Changed

- Retired the five Inventory Metabase dashboards and their collection through
  an idempotent, recoverable archive step instead of provisioning them.
- Removed the legacy Inventory materialized-view refresh from patch ingest,
  Agent Compliance collection, and Agent Compliance evaluation.

### Operational note

- This release does not delete Inventory database objects or history and does
  not change the Patching or Agent Compliance Metabase surfaces.

## [0.101.5] — 2026-08-03 — Retired Ninja correction eligibility

### Fixed

- Corrected the retired-scope operator to validate withdrawal ordering against
  source observation and last-seen times, not the later collector receipt time
  of restored historical evidence. Dry-run remains the default, and apply
  remains separately gated by an exact count and identity-set digest.

## [0.101.4] — 2026-08-03 — Ninja reader-cutover corrections

### Added

- Added a dry-run-by-default, aggregate-only operator for correcting retired
  `ninja_main` source evidence. Apply mode requires a separately approved exact
  record count and identity-set digest and preserves canonical devices, source
  links, daily rollups, raw evidence, and operator decisions.

### Changed

- Separated Ninja's direct operating-system boot time from its distinct
  hypervisor-reported boot measurement while retaining hypervisor power state.
- Made the Ninja device projection-v3 upgrade an explicit one-time history
  boundary so current evidence and its open history version use the same
  material contract even when the selected material hash is unchanged.
- Restricted current Ninja detail and health shadow views to their configured
  source instance, authoritative snapshot scopes, and projection versions;
  historical daily rollups remain available for inactive source records.

### Fixed

- Normalized the Operations entrypoint to Unix line endings during image
  builds so Docker images built from Windows worktrees start correctly.

### Operational note

- Legacy snapshot readers and writes remain authoritative. Deploying this
  release does not apply the retired-scope correction, promote generic readers,
  stop legacy snapshot writes, or delete historical data.

## [0.101.3] — 2026-08-03 — Historical Ninja evidence restoration

### Added

- Added a dry-run-by-default, completed-day-bounded operator tool that can
  restore stable inactive generic evidence and closed material history for
  withdrawn legacy Ninja devices without creating canonical devices, source
  links, or snapshot-run provenance.

### Operational note

- Restoring historical evidence and backfilling compact daily presence remain
  separately approved production data writes. Legacy snapshot deletion and
  cleanup remain out of scope.

## [0.101.2] — 2026-08-03 — Health evidence presence isolation

### Fixed

- Excluded Ninja `device-health` source records from the device-presence
  projection, preventing distinct endpoint evidence linked to the same device
  from colliding in the per-platform presence key while retaining the health
  evidence for patching and troubleshooting consumers.

## [0.101.1] — 2026-08-03 — Health shadow compatibility-key repair

### Fixed

- Namespace-qualified Ninja device-health's rollback-era compatibility key so
  its distinct stable source records can coexist with device-detail records
  under both the retained legacy uniqueness constraints and the stable-
  identity constraints.

## [0.101.0] — 2026-08-03 — Ninja snapshot storage expansion

### Added

- Added additive, tenant-scoped daily device-presence rollups with explicit
  snapshot-run or legacy-backfill provenance, RLS, and shadow compatibility
  views for Ninja device detail, health, and daily trend consumers.
- Added a dry-run-by-default, date-bounded, resumable operator tool for
  backfilling compact daily presence from legacy device snapshots.

### Changed

- Centralized deterministic complete-payload hashes and versioned material
  projections, excluding poll/contact noise while retaining meaningful Ninja
  device and health state.
- Expanded Ninja device current evidence with offline, reboot, boot-time,
  maintenance, and VM state, and added a distinct `device-health` current and
  material-history shadow write.

### Operational note

- Legacy Ninja snapshot writes and all current readers remain authoritative in
  this expansion release. Backfill, read cutover, legacy-write shutdown, and
  historical cleanup retain separate approval and verification gates.
- Closed material history keeps the existing 90-day default. Compact daily
  presence is initially retained without automatic deletion or partitioning;
  the measured design is reassessed after 30 days of steady-state evidence.

## [0.100.1] — 2026-08-03 — Snapshot run-start repair

### Fixed

- Made the raw snapshot-run writer explicitly initialize the non-null observed
  identity count instead of relying on Django's non-persistent migration-time
  default, and aligned the PostgreSQL regression fixture with production.

## [0.100.0] — 2026-08-03 — Stable observation identity cutover

### Changed

- Re-keyed generic current observations and open material history to the stable
  source-instance/namespace identity, keeping transport binding and Operations
  classification as mutable provenance and state.
- Reconciled complete snapshots from the single current record's run marker
  and run-start boundary instead of retaining one membership row per identity
  per poll. Partial, failed, and overlapping older runs cannot falsely
  withdraw newer evidence.
- Added compact per-run identity counts/digests and durable deciding-run
  provenance when source withdrawal closes a material-history interval.
- Kept legacy identity constraints and columns for comparison and rollback;
  destructive contract cleanup remains separately gated.
- Added an optional BuildKit CA secret for secure local image builds behind
  workstation HTTPS inspection; the CA is removed during the install layer and
  is not required or retained by normal production images.

## [0.99.2] — 2026-08-02 — Observation lock scaling

### Fixed

- Prevented large steady-state source snapshots from exhausting PostgreSQL's
  shared lock table: existing observations now serialize on their row locks,
  while only absent identities take the advisory lock and re-read required to
  close the new-row race.

## [0.99.1] — 2026-08-02 — Stable observation identity dual-write

### Changed

- Made Ninja, SentinelOne, ScreenConnect, LogMeIn, and Hudu observation paths
  populate the accepted stable source-instance/namespace identity alongside
  the still-authoritative legacy observation identity.
- Made snapshot runs derive their source instance from the transporting
  binding and record run start plus explicit full/partial completeness.
- Updated compatibility seed and backfill writers to preserve shadow identity
  coverage. Stable-key locks, uniqueness, readers, and reconciliation remain
  unchanged pending shadow comparison and the separately gated cutover.

## [0.99.0] — 2026-08-02 — Stable observation identity expansion

### Added

- Added nullable shadow identity and transport-provenance fields for current
  and historical Operations observations, plus source-instance, run-start,
  and explicit completeness fields for observation snapshot runs.
- Backfilled the accepted stable source namespaces for all current connector
  families without changing the deployed observation key, readers, writers,
  reconciliation, or canonical attachments.

## [0.98.8] — 2026-07-31 — Shared-serial resolver correctness

### Fixed

- Preserved the typed Device UUID when the resolver creates or refreshes a
  shared-serial finding, preventing the attribute-sync transaction from
  rolling back on a UUID/text mismatch.

## [0.98.7] — 2026-07-31 — Lifecycle-evidence policy activation

### Changed

- Activated direct-contact lifecycle evidence for RMM, EDR, and remote-access
  agents; combined direct-contact/reported-state evidence for hypervisor hosts;
  and reported-state evidence for VM guests, network devices, and monitor
  targets.
- Added a fail-closed activation migration that requires the reviewed entity
  types and the previously deployed inert registry state before applying the
  approved policy.

### Operational note

- Startup migration `0094` activates lifecycle automation. The first
  controlled platform-evaluator run after deployment performs the approved
  reconciliation and records every automatic transition in the append-only
  audit stream.

## [0.98.6] — 2026-07-31 — Inert lifecycle-evidence policy and transition audit

### Added

- A deny-by-default `lifecycle_evidence_mode` registry capability with
  distinct direct-contact, reported-state, and combined evidence modes.
- Data-quality findings for unknown reported lifecycle state and equal-time
  reported-state conflicts.
- Atomic `lifecycle.transition` events in the generic append-only Operations
  audit stream.
- A tenant-scoped, read-only **Admin → System → Lifecycle policy** page showing
  registry policy and audited transitions.

### Changed

- The evaluator now selects the newest qualified lifecycle evidence, preferring
  direct agent contact only on an exact timestamp tie and treating recognized
  VM power/reported state as valid lower-fidelity evidence.
- Registry writes are deployment-controlled, and runtime audit roles are
  append-only.

### Operational note

- Migration `0093` intentionally leaves every lifecycle evidence mode at
  `none`. Automatic lifecycle-status updates are paused until a separately
  approved activation release; collection, observations, coverage, and other
  evaluator work continue, and existing lifecycle states are unchanged.
- The `origin` push, Portainer redeploy, and startup migration are one coupled
  production action in the current deployment model. Pending migrations must
  be reviewed and included in the approval before pushing `origin`.

## [0.98.5] — 2026-07-27 — Software UX: clickable risk strip, action buttons, category columns, richer filters

### Changed
- **Risk distribution strip** on the Software Overview is now fully clickable:
  each colored segment and its legend label links to Products filtered by
  the matching safety level (`?safety=high/medium/low/clean/unknown`).
- **Publishers list** — added Category column (resolved from
  `publisher_categories` rules); replaced the per-row dropdown+Apply with
  direct **Allow / Block / Review** buttons; the new category column is
  sortable.
- **Decisions queue** — added Search (product/publisher substring) and
  Decision-status filter to the filter bar; replaced the per-row
  dropdown+Apply forms with **Allow / Block / Review** buttons for the
  product scope and **Trust pub. / Block pub.** for publisher scope.
- **Cleanup** (tech checklist) — category now shown inline under each
  product name when available (sourced from `software_catalog`).
- **User exposure** — added User search and Reason-kind filter; category
  now shown inline per item where available.

## [0.98.4] — 2026-07-27 — Client overview polish

### Changed
- **Client overview** (`org_index.html`): removed placeholder "future-note"
  banners, added plain-language descriptions to the Recent changes and
  Configuration snapshot sections, improved label text ("Service requirements"
  → "Requirement profile", "Data mappings" → "Connected sources"), linked the
  Requirement profile label directly to its config page, and updated the
  call-to-action to "Manage requirements →".

## [0.98.3] — 2026-07-27 — Software nav: workflow verbs, retire Decisions tab

### Changed
- **Software sub-nav uses verbs / concepts, not admin nouns.**
  Overview / Products / Publishers / **Cleanup** (was Tech checklist)
  / **User exposure** (was User risk) / **Activity** (was Log).
  The standalone "Decisions" tab is retired — its list was a
  products-filtered-for-flagged view, which is now the built-in
  **Review flagged products** workflow tile and a `?flagged=1`
  filter on Products. Old `/software/decisions/` URL still resolves
  for direct bookmarks.
- **Overview workflow tiles** re-phrased with verb-first labels:
  "Review flagged products" (was Decisions queue), "Activity" (was
  Decision log), "Cleanup by device" (was Tech checklist), "User
  exposure" (was User risk).
- **"Where you stand" summary card** replaces "Decisions summary" at
  the bottom of the Overview. Copy switched to Allow / Block / Review
  / Waiting.
- **Admin overview + admin nav** point at the new
  `Products?flagged=1` path for the software review workflow. Card
  titled "Review flagged software".

## [0.98.2] — 2026-07-27 — Decision log, Allow/Block/Review labels, tech-checklist filters

### Added
- **Software Decision log** at `/software/decisions/log/` — a
  chronological audit of every `SoftwareDecision` regardless of
  whether the corresponding product still has a finding. Filters:
  free-text search over product / publisher / reason, scope (global /
  client / device / publisher-scope / product-scope), and decision.
  New "Log" tab in the Software sub-nav.
- **Per-column filters on Tech Checklist**: search (device / client
  / product / publisher), role, OS group, reason kind (e.g.
  `suspicious_name`, `decision_reject`), and the pre-existing client
  filter. Server-side WHERE for role / OS / client, Python-side for
  the free-text and reason kind.

### Changed
- **Decision labels rendered as Allow / Block / Review / Trust
  publisher** across every operator-facing surface. Internal DB
  values (`approve` / `reject` / `investigate` / `approve_publisher`)
  unchanged — this is a `human_labels` mapping, no data migration.

## [0.98.1] — 2026-07-27 — Matcher upgrade + matview refresh hooks

### Changed
- **Matcher consults `intel_matcher_hints`.** Sub-component canonical
  names that match any `ignore_sub_component` regex skip CVE matching
  entirely; `require_third_token` vendors require a distinctive third
  token beyond `vendor + product` before a tier-1 match fires. Both
  hint lists are data-driven and admin-editable.
- **Version-aware matcher.** A year token (2010..2035) or semver
  major/minor prefix parsed from the canonical name filters CPE
  candidates to those whose `version` component starts with that
  string. Version-agnostic CPEs stay in the set as a safety net.
- **`operations.v_software_safety` refreshes automatically** at three
  points:
  1. End of the intel matcher run (`ingest.intel.matcher.run_once`).
  2. End of the software classifier cycle
     (`run_software_classify_once` in ingest).
  3. After every operator decision write (`software_decision_create`
     and `software_decision_bulk` in operations).
  All calls are best-effort — a matview refresh failure never
  bubbles up as a request or run error.

## [0.98.0] — 2026-07-27 — Publisher aliases, category taxonomy, matcher hints, matview

### Added
- **`operations.publisher_aliases`** (model + admin) — canonical
  publisher-name normalization. Raw variants preserved and shown on
  the detail page; the alias is used for aggregation and matching
  only. Every rule is a row, editable in Django admin.
- **`operations.publisher_categories`** (model + admin) — data-driven
  default categorization: any product whose publisher matches a
  pattern is auto-tagged with the row's categories. Applied on top of
  the per-title catalog entries.
- **`operations.intel_matcher_hints`** (model + admin) — two kinds of
  matcher tuning:
  * `require_third_token` — for common vendors (Microsoft, Adobe,
    Google, Oracle, IBM, Cisco, VMware, Citrix) a canonical name must
    carry a distinctive third token before a CVE match fires. Blocks
    `Microsoft Office Shared MUI` from inheriting every Office CVE.
  * `ignore_sub_component` — regex patterns for support / language /
    proofing / redistributable sub-components that inherit risk from
    their parent, not from the CVE database directly.
- **Documented canonical MSP taxonomy** on `PublisherCategory.categories`
  help text: `system`, `driver`, `security`, `av`, `edr`, `browser`,
  `productivity`, `communication`, `media`, `development`, `runtime`,
  `remote-access`, `management`, `rmm`, `backup`, `virtualization`,
  `storage`, `networking`, `database`, `engineering`, `utility`.
- **Migration 0087** seeds ~55 publisher aliases, ~47 publisher →
  category rules, and ~24 matcher hints — everything editable in
  admin.

### Changed
- **`operations.v_software_safety` is now a materialised view** —
  same shape and columns but backed by a matview with a unique
  index on `(tenant_id, canonical_name)` and secondary indexes on
  band and resolved publisher. Reads become index lookups; the
  700-900 ms per-scan cost disappears from the software pages.
- **Publisher-approve owns the band.** If the operator (or an alias-
  resolved publisher decision) has approved a title or its publisher,
  the band is `clean` regardless of CVE matches. Publisher-approve
  score decrement raised from 60 → 100 so the composite stays
  consistent.
- **CVE recency filter.** The band-driving `max_cvss` / `max_epss` now
  look at CVEs modified in the last 3 years or KEV-flagged. Older
  CVEs stay counted in `cve_count` (informational) but do not paint
  a modern install red.
- **Publisher aliasing feeds the OSINT + decision joins.** The
  resolved publisher (via `publisher_aliases`) drives publisher-scope
  matching, so `Microsoft Corporation`, `Microsoft Corp.`,
  `Microsoft, Inc.` all resolve to `Microsoft` for join purposes.
  Raw publisher stays visible on every detail page.

### Notes
- The matview is not yet auto-refreshed; the migration creates it
  and populates it. A refresh hook lands in the follow-up commits at
  the end of the intel matcher, at software-classify, and after
  `software_decision_create`. Until then the matview reflects the
  state at migration time; run `/admin/jobs/` → Intel matcher →
  Run now once and it will start reflecting fresh data.

## [0.97.9] — 2026-07-27 — Software nav split: Overview + Products

### Changed
- **Software nav split.** The Products tab used to point at
  `/software/`, which is really a dashboard with the products list
  tucked away under "Browse all products". Renamed that landing to
  **Overview**, and added a real **Products** tab at
  `/software/products/` that opens the products list directly.
- **`software_page` view refactored** — the request-handling body moved
  into a shared `_software_page_data(request)` helper. `software_page`
  now renders Overview (dashboard tiles + workflows + distribution +
  this-week + recent installs). `software_products` renders the
  full products table with per-column filters. Same context, two
  templates.
- **New per-column filters on the Products page**: search on product,
  search on publisher, minimum device count, risk band, decision,
  category chips. Every column that carries a decision or a category
  now has its own control.
- **Overview page shrinks.** Products table removed from the Overview
  (was collapsed at the bottom); Overview is now purely a dashboard.

### Notes
- Decisions are still written to the same `operations.software_decisions`
  table from every entry point (Products, Publishers, Decisions queue,
  bulk actions). The Decisions queue is a *pending* queue, not a
  decision log — a dedicated decision-log surface is on the follow-up
  list.

## [0.97.8] — 2026-07-27 — `/software/?safety=X` worker-timeout 500 fix

### Fixed
- **`/software/?safety=high` (or any risk band) 500'd via gunicorn
  worker timeout** — the risk-band filter used an
  `EXISTS (SELECT 1 FROM v_software_safety WHERE canonical=…)`
  clause on the products query, which re-evaluated the multi-CTE
  risk view once per product row. With 20 k products, that blew
  through the 30 s gunicorn timeout. Reordered the request: fetch
  `v_software_safety` **once** at the top (already done for the
  distribution numbers), extract the canonical set for the target
  band in Python, then pass that set as a single `ANY(%s::text[])`
  filter to the products query. Zero extra view scans. Removed the
  duplicate second fetch that was still on the code path.

## [0.97.7] — 2026-07-27 — On-demand card links point at ingest:8090

### Fixed
- **On-demand scoped-run cards on `/admin/jobs/` returned 404** —
  their `href`s were current-host relative (`/run/sources/enqueue`),
  which resolved against operations:3002, not the ingest container
  where those endpoints actually live. Cards now use
  `ingest_public_url` (defaults to `<scheme>://<current host>:8090`,
  overridable via the `INGEST_PUBLIC_URL` env var for setups behind
  a different reverse proxy).

## [0.97.6] — 2026-07-26 — Ingest ready-state bug + unified software surfaces

### Fixed
- **`Run now` returned 503 for every job** — when I added
  `_intel_catchup()` in 0.97.0, the "block forever" tail of `main()`
  got captured inside the new function's body due to a misplaced
  indentation. The main thread never returned from `_intel_catchup`,
  so `_READY.set()` never fired and every `/run/*` endpoint answered
  "still starting". Extracted the block-forever back into `main()`
  after `_READY.set()`. Every Run-now now works after the next
  ingest restart.

### Changed (software surfaces — visual family)
- **New shared style include** `_sw_style.html` provides the same
  page header, filter bar, bulk-action bar, data table, pill styles
  (risk + decision), and empty-state look for every software surface
  (Products / Publishers / Decisions / Tech checklist / User risk).
  Included on the pages that had drifted apart in styling.
- **Publishers page rebuilt** on the shared style with a proper
  filter bar (search + decision-status dropdown), bulk-select
  checkboxes with an "Apply to selected publishers" button, and a
  per-row single-picker matching the decisions queue exactly.

## [0.97.5] — 2026-07-26 — Winget/Chocolatey endpoints, per-source jobs, subject_layer default

### Fixed
- **Platform evaluator failed with "null value in column subject_layer"** —
  the `findings.subject_layer` column was `NOT NULL` without a DB
  default. The Django model declares `default=""` but raw-SQL
  writers in `ingest/evaluator.py` etc. bypass the ORM. Migration
  `0085` sets `DEFAULT ''` at the DB level and backfills any nulls,
  fixing every writer without code changes. Evaluator's own INSERT
  now also lists the column explicitly.
- **Winget enrichment** — Microsoft's `cdn.winget.microsoft.com`
  endpoint returns 405 for third-party POSTs. Switched to the
  community `api.winget.run/v2/packages` REST API (same manifest
  data, GET-friendly, no auth). Verified 200 with real Packages
  response.
- **Chocolatey enrichment** — the `/Search()` OData endpoint 400s.
  Switched to `/Packages()?$filter=IsLatestVersion&$top=5&searchTerm='…'`,
  which returns proper Atom feed XML.

### Added
- **Jobs page — per-source rows** — every distinct
  `source.<Platform>[.<Instance>]` kind that ever ran shows up as
  its own row under Source Ingest. The Run-now button is replaced
  with a "Scoped run…" link that opens the ingest form for that
  category (per-instance triggers go through the org / device
  selector).
- **On-demand scoped runs section** at the bottom of `/admin/jobs/` —
  three cards linking to the ingest container's org / device selector
  forms: Software inventory (queued), Source ingest (per-instance),
  Direct scoped software run (inline).

## [0.97.4] — 2026-07-26 — /software perf: fetch v_software_safety once

### Fixed
- **/software loads slowly** — once the intel layer populated CVEs and
  matches, the fleet page called `operations.v_software_safety` three
  times per request (per-shown-title lookup, high-band count, band
  distribution) plus a fourth "new-high-risk-this-week" JOIN. Each
  view evaluation was ~700-900 ms, adding up to 3-4 s per render.
  Now fetch the whole view **once** at the start of the request and
  derive `safety_by_title`, `high_risk_titles`, `risk_distribution`,
  and `this_week.new_high_risk` from that one snapshot in Python.

## [0.97.3] — 2026-07-26 — Jobs page: groups, run-all, correct kind mapping, recent activity

### Fixed
- **Every non-intel job showed "Never run"** — the catalog's
  `status_key`s did not match the actual `run_log.kind` values
  emitted by the writers (`software_classifier`, `patch_findings`,
  `platform_evaluator`, `parity_check`, `source.<Platform>`).
  Corrected. Source-ingest jobs use a new `run_log_like` status
  source that prefix-matches (e.g. `source.` catches every per-instance
  source row).

### Added
- **Run everything now** button and per-category **Run all in this
  category** buttons on `/admin/jobs/` — POST to
  `/admin/jobs/run-all/`. Both prompt for confirmation.
- **Recent activity panel** at the bottom of the jobs page — last 25
  runs across `run_log` and `intel_ingest_status`, so an operator
  who clicks Run-now can see the run appear when it completes.
- **Auto-refresh every 20 s** on the jobs page (pauseable with
  `?live=off`). Uses JS `setTimeout` so no `base.html` change needed.

### Changed
- Jobs page renders one section per category (Source ingest / Intel /
  Evaluators / Notifications) instead of a flat list.
- Added `Parity check` to the catalog.
- Category-level "Run all" buttons appear both above and inline with
  each section heading.

## [0.97.2] — 2026-07-26 — Admin hub — every admin surface in one place

### Changed
- **`/admin/overview/` reshape** — the Admin landing was three thin
  sections; now it is a proper hub with SVG-iconned cards grouped by
  workflow:
  - **Review queues** — Client candidates, Merge candidates, Software
    decisions, All findings (with open counts).
  - **Software** — Products, Publishers, Tech checklist, User risk,
    Classifier rules (with enabled-rule count).
  - **Policy &amp; configuration** — Service requirements, Device
    status thresholds, Alert rules, Suppressions.
  - **Data &amp; integrations** — Sources (stale / total), Jobs (with
    intel connector ok / failed / not-run counts), Ingest health,
    Coverage, Patching.
  - **System** — Django admin.
- Every tile is a link with a short description; badge counts are
  computed in-view with cheap queries and tolerated to fail on fresh
  installs (intel counters guarded by try / except).

## [0.97.1] — 2026-07-26 — EPSS endpoint + matcher token intersection

### Fixed
- **EPSS ingest** — the daily CSV moved from `epss.cyentia.com` to
  `epss.empiricalsecurity.com` (301 redirect). Pointed the connector
  at the new URL and enabled `follow_redirects=True` so the next
  domain change is also handled transparently.
- **Intel matcher matched zero products** — the day-one normalizer
  concatenated every canonical name into a single token
  (`googlechrome` etc.) and never lined up with CPE product names
  (`chrome`). Rewrote the matcher as token-intersection: split every
  canonical on alphanumeric boundaries, treat the resulting tokens as
  a set, tier-1 match when a `(vendor, product)` from `intel.cpes`
  falls fully inside the token set, and tier-2 fallback on a
  distinctive product-only token (>= 4 chars, alphabetic, not in a
  short generic stop list). Uses `affected_cpes ?| candidates::text[]`
  (GIN-indexed jsonb operator) so per-canonical lookup stays sub-ms.

### Notes
- The next intel matcher run (either the natural 6-hour tick or a
  manual "Run now" from `/admin/jobs/` for the Intel: title × CVE
  matcher row) will populate `operations.cve_match` for every
  canonical whose vendor + product resolve inside the CPE dictionary.

## [0.97.0] — 2026-07-26 — Jobs page, intel catch-up, bulk decisions, software sub-nav

### Added
- **Jobs page (`/admin/jobs/`)** — every scheduled job (source ingest,
  intel connectors, evaluators, notifications) with last-run status,
  age, rows touched, last error, and a **Run now** button that POSTs
  to the ingest container's `/run/<slug>` HTTP endpoint. Category +
  status filters (ok / stale / failed / never run). Reachable from
  the "Jobs" tab under the Integrations admin nav.
- **Ingest `/run/intel-*` HTTP endpoints** for every intel connector
  (kev / nvd / cpe-dict / epss / matcher / winget / chocolatey / otx /
  abusech). Same 202-Accepted background-thread pattern the existing
  `/run/*` endpoints already use.
- **Intel catch-up on ingest startup** — any connector with no
  successful run in `operations.intel_ingest_status` fires in a
  background thread when the scheduler comes up, so a fresh deploy
  doesn't wait hours for the first natural tick.
- **Software sub-nav** (`_software_tabs.html`) included on every
  software surface (Products, Publishers, Decisions, Tech checklist,
  User risk). One consistent nav strip; each view sets `software_tab`
  to highlight the active page.
- **Publisher column + publisher-scope apply on the decisions queue**
  — the current publisher-scope decision, if any, is rendered under
  the product's own decision. Per-row picker has separate "Product"
  and "Publisher" apply buttons.
- **Bulk actions on the decisions queue** — checkboxes on every row
  plus a bulk bar with a "Apply as: this product only / this
  publisher (every product)" scope selector. Single POST to
  `/software/decisions/bulk/` with the chosen decision applied to
  every selection. Audited per-row.

### Fixed
- **`/software/` counted publisher-scope decisions as products** —
  approving two publishers surfaced as "2 approved products".
  Approved / rejected / investigating are now
  `COUNT(DISTINCT canonical_name)` where the product **or its
  publisher** has a global-scope decision.

## [0.96.1] — 2026-07-25 — Fix operations import: swap `requests` for stdlib `urllib`

### Fixed
- **Operations container crash-loop after 0.94.0 / 0.96.0** — the
  on-demand VirusTotal lookup imported `requests`, which isn't in the
  deployed operations image. Rewrote `_lookup_virustotal` on top of
  stdlib `urllib.request` so nothing outside the standard library is
  required. Careless-mistakes rule #10: verify against the deployed
  image, not the local venv.

## [0.96.0] — 2026-07-24 — Software dashboard reshape + auto-intel on software cycle

### Changed (operator-facing)
- **`/software/` is now a proper dashboard.** Overview KPIs, risk +
  decision distribution strips ("where the fleet stands"), a "This
  week" summary card (new products, new high-risk, top new product),
  workflow tiles with real state ("undecided", "awaiting", "devices",
  "candidates") plus inline SVG icons instead of single-letter
  monograms. Products table moved to the bottom under a collapsed
  "Browse all products" disclosure that auto-opens when a filter is
  applied.
- **Terminology pass**: "Titles" renamed to "Products" throughout the
  operator-facing page and search placeholder; "Open items" reworded;
  workflow card descriptions phrased for humans.

### Changed (behavior)
- **Intel matcher + Winget + Chocolatey enrichers now fire on the
  software classify cycle**, before the classifier itself. Newly
  ingested products get scored and enriched in the same run instead of
  waiting for the next 6-hour intel cadence. Steps are best-effort —
  a broken intel connector never blocks the classifier.

## [0.95.0] — 2026-07-24 — known_malicious_hint finding (Batch H)

### Added
- **`known_malicious_hint` FindingType** (migration `0084`) — fires per
  device when the installed title (or its publisher) has accumulated
  ≥ N open threat-intel hits (OTX + MalwareBazaar + ThreatFox) and the
  operator has not approved. Explicitly a low-severity **hint** — OSINT
  is community-curated and noisy — with two `EvaluatorConfig` knobs
  (`known_malicious_hint_min_hits` default 3,
  `known_malicious_hint_severity` default low).
- **Classifier step 9** in `ingest/software_findings.py` — new emit
  path with a helper `_load_threat_hit_counts` that folds title-scope
  and matched publisher-scope signals into a per-canonical count.

Software safety-intel track (Batches A–H) is now complete.

## [0.94.0] — 2026-07-24 — Software dashboard reshape, Risk labels, on-demand lookup (Batch G)

### Fixed
- **`/software/` worker timeout on some renders** — split the risk lookup
  into its own atomic block, gated behind a `to_regclass` probe so the
  page still loads when the intel view hasn't been migrated yet.
- **"Whitelist" chip on the fleet page** was surfacing a legacy catalog
  category value; hidden from the chip strip. Trust now lives in
  decisions, not the catalog.

### Changed (operator-facing)
- **Fleet page reshape** — high-level dashboard with two rows of tiles:
  numeric overview (Titles, Unclassified, Awaiting decision, High risk,
  Open items) and workflow launchers (Publishers, Decisions queue, Tech
  checklist, User risk, Whitelist suggestions). The titles table trims
  to Title + publisher subline, Devices, Risk, Decision, Actions — no
  more overflow, sortable, hover-highlighted.
- **Product name display** — canonical names and publishers rendered
  with `title` casing on the fleet, publisher, and detail pages so
  lowercase raw values ("google chrome") don't look raw.
- **Risk labels reworked** — "Clean" is reserved for titles the operator
  has approved. Titles with no risk data and no approval now show
  "Not yet checked" (new `unknown` band). Column headers changed from
  "Safety" to "Risk", tooltips use "known vulnerabilities" /
  "actively exploited" / "threat-intel matches".

### Added
- **On-demand VirusTotal lookup** — button on the title Risk card. Per
  operator: 10 lookups/hour cap, 48-hour cache in
  `operations.title_intel_cache`. Runs against the free-tier VirusTotal
  API using the operator-supplied `VT_API_KEY` from the deploy env.
  Result summary flashed as a Django message; full JSON stored in
  cache.
- **New URL** `software/title/<name>/lookup/<source>/`.
- **Migration `0083`** updates the risk view to distinguish `clean`
  (approved by operator) from `unknown` (no risk data on record).

## [0.93.0] — 2026-07-24 — Title Risk panel + vulnerable_software finding (Batch F)

### Added
- **Risk panel on `/software/title/<name>/`** — composite risk band,
  score, known-vulnerability counts, worst severity, exploit likelihood
  (EPSS), threat-intel match counts on title and publisher, and a
  community-tag row merged from Winget/Chocolatey signals.
- **Known vulnerabilities table** on the title page — top 25 CVEs by
  active exploitation + severity, deep-linked to nvd.nist.gov.
- **Threat-intel matches list** on the title page — one row per source
  hit with severity and observed time.
- **`vulnerable_software` FindingType** (migration `0082`) — fires per
  device for installed titles that match a KEV-flagged CVE or a CVSS ≥
  cutoff. Severity ranks KEV as critical, CVSS-severe as high.
  Suppressed by approve / approve_publisher decisions since those
  express operator acceptance of the risk.
- **Classifier step 8** — new emit path in
  `ingest/software_findings.py` with three new EvaluatorConfig knobs
  (`vulnerable_software_enabled`, `_cvss_cutoff` default 7.0, per-tier
  severity overrides).

### Changed
- Human-friendly operator labels: **"Safety"** renamed to **"Risk"** in
  every visible surface (column, tile, card, pill). Internal names
  (`v_software_safety`, `safety_signal`, template classes) unchanged.
- Fleet Risk column shows "High risk / Medium risk / Low risk / Clean"
  in words; tooltip uses "known vulnerabilities", "actively exploited",
  and "threat-intel matches" instead of CVE / KEV / OSINT.

## [0.92.0] — 2026-07-24 — Composite safety score + fleet-page surface (Batch E)

### Added
- **`operations.v_software_safety` view** (migration `0081`) — per
  canonical title, composite safety score 0..100, safety band
  (clean / low / medium / high), matched CVE / KEV / OSINT-hit counts,
  and title/publisher-scope decision status. Weights follow ADR 0008.
- **Safety column on `/software/`** — pill showing band + score, tooltip
  with CVE / KEV / OSINT breakdown. Sortable.
- **Safety filter (`?safety=high` etc.)** on the fleet page.
- **Safety tile on `/software/`** — high-band title count links to the
  filtered view.

## [0.91.0] — 2026-07-24 — Intel OSINT: OTX + abuse.ch (Batch D)

### Added
- **AlienVault OTX ingest** (`ingest/intel/otx.py`) — pulls recently
  modified subscribed pulses, matches indicators + tags against
  canonical software names and publishers we track. Signals stored at
  `severity='low'` (community-curated, noisy).
- **abuse.ch MalwareBazaar + ThreatFox ingest** (`ingest/intel/abusech.py`) —
  pulls the recent dump files per abuse.ch's fair-use guidance (single
  HTTPS GET each, no per-hash API loops). Matches on publisher
  signature and filename tokens; signals stored at `severity='medium'`.
- **Two new APScheduler cycles** on `INTEL_OSINT_SCHEDULE_HOURS`.

## [0.90.0] — 2026-07-24 — Intel catalog enrichment: Winget + Chocolatey (Batch C)

### Added
- **Winget enrichment** (`ingest/intel/winget.py`) — per-canonical query
  against the Windows Package Manager REST search endpoint (same one
  the `winget` CLI uses). Only titles observed in the fleet, and only
  those without a fresh signal, so the update set stays bounded. Tags,
  publishers, and package identifiers land on
  `operations.safety_signal` as `source='winget', signal_type='category'`.
- **Chocolatey enrichment** (`ingest/intel/chocolatey.py`) — same
  shape, hitting the community OData search feed. Tags aggregated per
  title.
- **Scheduler wiring** — both connectors run on `INTEL_CATALOG_SCHEDULE_HOURS`
  under the `INTEL_ENABLED` master flag with independent enable flags.

## [0.89.0] — 2026-07-24 — Intel connectors: NVD + CPE + KEV + EPSS + matcher (Batch B)

### Added
- **NVD v2 delta ingest** (`ingest/intel/nvd.py`) — paginated
  `lastModStartDate` cursor, 120-day first-run lookback, 40-page safety
  cap, 429-aware backoff, rate-limited to the free-tier ceiling
  depending on whether an API key is present.
- **NIST CPE 2.3 dictionary ingest** (`ingest/intel/cpe_dict.py`) —
  same paginated shape, populates `intel.cpes` with lowered
  vendor/product/version tokens for the matcher.
- **CISA KEV ingest** (`ingest/intel/cisa_kev.py`) — single JSON pull,
  upserts `kev_flag / kev_added_at / kev_notes` on every cataloged
  CVE and clears the flag on rows CISA removed from the list.
- **FIRST.org EPSS ingest** (`ingest/intel/epss.py`) — daily gzipped
  CSV, only updates CVEs already present in `intel.cves` so the
  update set stays bounded.
- **Conservative day-one matcher** (`ingest/intel/matcher.py`) —
  normalizes canonical software names to alphanum tokens, exact-matches
  against CPE `product`, then joins to CVEs via `affected_cpes ?|`.
  Marks every hit `confidence='high', match_kind='cpe_exact'`.
- **APScheduler wiring** — five new cycles under the `INTEL_ENABLED`
  master flag with per-connector on/off flags and independent cadences.
  Each cycle is single-instance so a slow run doesn't stack.

### Notes
- All new external calls are behind `INTEL_ENABLED`, which defaults to
  `false`. Set it once the six free keys are in the deploy env and the
  operator wants to start pulling.
- Every connector wraps its run in `record_run`, so
  `operations.intel_ingest_status` shows the last outcome, error, and
  rows touched per source — nothing hidden.

## [0.88.0] — 2026-07-24 — Software safety intel: schema + ADR (Batch A)

### Added
- **ADR 0008 — Software safety intel layer.** Documents the
  free-tier-bulk + free-on-demand strategy, source list, matcher and
  scoring approach.
- **`intel` Postgres schema** (sql migration `072_intel_schema.sql`) —
  isolates raw threat data from operations, mirroring how
  `ninja_patches` / `ninja_activities` separate source-specific stores.
  Tables: `intel.cves`, `intel.cpes`.
- **Operations-owned tables** — `operations.cve_match`,
  `operations.safety_signal`, `operations.title_intel_cache`,
  `operations.intel_ingest_status`.
- **`ingest/intel/` package skeleton** with a `record_run` context
  manager wrapping every connector so the last-run status, error, and
  rows-touched surface on `intel_ingest_status` (nothing hidden).
- **Six `INTEL_*` env knobs + six free API keys** wired into
  `ingest.config.Settings` (all default off until Batch B enables the
  first connector).

## [0.87.0] — 2026-07-24 — Software user-risk view

### Added
- **`/software/user-risk/`** — per-user rollup of software checklist
  items on the device the user last logged into. Anchored on Ninja's
  `lastLoggedInUser` (latest snapshot per device via
  `ninja_core.device_snapshots`) joined through `device_links`. Users
  who log into multiple devices are aggregated across all of them, with
  the checklist items grouped per-device. Multi-client filter, CSV
  export, top-500 cap.
- **User risk tile on `/software/`**.

## [0.86.0] — 2026-07-24 — Software Tech Checklist

### Added
- **`/software/tech-checklist/`** — per-device curated cleanup queue,
  the operator-facing analog of the legacy analyzer's "Tech Checklist"
  sheet. Combines active software findings (all software finding types
  except `whitelist_suggestion`) with installations that hit a
  reject/investigate decision at title-scope or publisher-scope. One
  card per device with client / role / OS metadata, a per-item reason
  line, and a link straight to the device detail. Multi-client filter,
  CSV export, top-500 cap.
- **Tech Checklist tile on `/software/`** links to the new page.

## [0.85.0] — 2026-07-24 — Whitelist Suggestions

### Added
- **`whitelist_suggestion` FindingType** (migration `0080`, seeded under
  the software category). Fires for uncategorized + undecided titles
  installed on ≥ N devices fleet-wide — the "widespread but nobody has
  decided on it" review queue.
- **Software classifier step 7** — the ingest evaluator emits
  `whitelist_suggestion` from the same per-install loop as the existing
  seven steps, gated by three new `EvaluatorConfig` knobs
  (`whitelist_suggestion_enabled` default true,
  `whitelist_suggestion_min_devices` default 10,
  `whitelist_suggestion_severity` default `low`).
- **Whitelist suggestions tile on `/software/`** — deduped by
  canonical_name, kept separate from the "flagged installations" tile
  so review candidates don't inflate the problem count.

## [0.84.0] — 2026-07-24 — Software publisher rollup + publisher-scope decisions

### Added
- **`/software/publishers/` list.** One row per observed publisher with
  installations, distinct titles, distinct devices, distinct clients,
  last observed, current global publisher-scope decision, and an inline
  Approve/Reject/Investigate/Approve-publisher form.
- **`/software/publishers/<publisher>/` detail.** Summary tiles, a
  publisher-scope decision form, the full title list from that publisher
  with per-title decision state and inline title-scope decision actions,
  and publisher-scope decision history at client/device tiers.
- **Publishers tile on `/software/`** and clickable publisher cells on the
  fleet titles table and on the per-title detail page.

### Changed
- **`SoftwareDecision.publisher` field** (migration `0079`). Decisions now
  bind to either a canonical_name (title-scope) or a publisher
  (publisher-scope, applies to every title from that publisher including
  titles first observed after the decision). A `CheckConstraint` enforces
  exactly one of the two match keys is set.
- **Classifier decision resolver** (`ingest/software_findings.py`) now
  honours publisher-scope tiers: title-scope wins (device > client >
  global), publisher-scope is the fallback (device > client > global).
  Publisher-approving no longer requires per-title decisions to actually
  suppress findings across the publisher's catalog.
- **Fleet page `?decision=` filter** now considers publisher-scope
  approvals/rejections/pending when computing the title's disposition.
- **`software_decision_create`** accepts a `publisher` POST param and
  enforces the XOR at the form level.

## [0.83.0] — 2026-07-24 — Software title detail + row-level decisions

### Added
- **`/software/title/<name>/` detail page.** Per-canonical drill-through from
  the fleet titles table. Summary tiles (installations, devices, clients,
  versions, first/last observed), catalog metadata (categories, EOL, notes),
  global-scope decision form, version breakdown, publisher breakdown, install
  locations, per-device installation list with device-scope decision actions,
  related active findings, and full client/device-scope decision history.
- **Row-level decision actions on `/software/`.** Inline
  Approve/Reject/Investigate/Approve-Publisher form on every fleet-titles row,
  posting to the shared `software_decision_create` endpoint with a `next`
  redirect so the operator lands back where they were.
- **Per-org software table** links each title to the detail page.

### Changed
- `software_decision_create` now honours a `next` POST parameter (relative
  URLs only, to avoid open-redirects), letting decision forms across the
  Software surfaces return the operator to their origin page.

### Performance
- **Functional index** `software_installations_current_lower_canonical_idx`
  on `(tenant_id, LOWER(canonical_name)) WHERE deleted_at IS NULL AND
  stale_since IS NULL` (migration `0078`). Every case-insensitive lookup
  against the installations table now uses an index scan; measured Google
  Chrome install-list query drops from 588 ms (parallel seq scan of 432k
  rows) to 112 ms (index scan).

## [0.82.2] — 2026-07-24 — Grant SELECT on `device_patch_activity`

### Fixed
- **`/patching/` returned HTTP 500 after 0.82.1 deploy** because migration
  070 created `ninja_patches.device_patch_activity` without the `GRANT SELECT`
  statements the sibling matviews carry (`operations_app`,
  `operations_readonly`, `metabase_ro`). Migration `071` grants those roles
  the same read access they already have on `device_patch_signal`,
  `current_patch_state`, and `latest_install_outcome`.

## [0.82.1] — 2026-07-24 — Patching page perf: matview-backed posture rollup

### Fixed
- **`/patching/` slow to load.** The posture status cards were computed by
  a CTE that (a) aggregated `MAX(...)` over 467k `ninja_patches.patch_facts`
  rows to derive per-device `last_patch_activity_at`, and (b) executed twice
  per request (once for fleet totals, once for the per-client rollup).
  Deployed-DB dry-run measured the rewritten path end-to-end at 123 ms.

### Added
- **`ninja_patches.device_patch_activity` matview** (`sql/migrations/070`) —
  one row per Ninja device with `last_patch_activity_at`, refreshed alongside
  the existing patch summary matviews at the end of each patch ingest cycle
  (`ingest/patches/ingest.py`).

### Changed
- **`patching_queue` view** now reads `device_patch_activity` instead of
  aggregating `patch_facts` at request time, and consolidates the fleet
  totals and per-client posture into a single `GROUPING SETS` query with
  Python-side split.

## [0.82.0] — 2026-07-22 — Device Detail Raw tab: canonical field matrix + Ninja `raw_data` fidelity

### Fixed
- **Ninja `raw_data` empty on every observation.** `ingest/core/devices.py`
  wrote `Json({})` for every Ninja `entity_observation`, so the Device
  Detail Raw tab could not show source fields for Ninja (the trigger
  that opened ADR-0007). The Ninja API row is now side-banded via
  `raw_by_id` from the fetch loop through `_write_ninja_observations`
  and stored on `_current.raw_data`. Also applies to org observations,
  which now carry `ninja_core.organizations.data`. Existing rows
  overwrite on the next Ninja cycle.

### Added
- **Canonical field matrix on Device Detail → Identity & raw.** Rewrite
  of the "Common fields across sources" section to read from
  `canonical_data` (the normalized per-source projection) instead of
  `raw_data`. Every source rewrites the same concepts (hostname,
  os_name, serial_number, macs, is_online, etc.) into the same
  canonical key names, so the matrix compares values across sources
  directly. Every canonical field appears — even if only one source
  reports it — with a "1 source" badge so operators see the whole
  normalized picture. Cross-source disagreements still get the amber
  highlight + ⚠ prefix. Values render legibly: lists comma-joined
  (macs, tags), booleans as yes/no, empty as em dash, nested dicts as
  compact JSON.
- **Source-native fields** section replaces the previous "Per-source
  details" — for each source snapshot, lists the raw_data keys not
  represented in canonical_data. Alias-hiding is case-insensitive: raw
  `hostName` normalizes to `hostname` and is hidden when canonical
  already has `hostname`. Non-alias fields like `systemName`,
  `dnsName`, source-specific IDs stay visible.
- Additional category keywords for the field grouping: `macs`, `vmuuid`,
  `powerstate`, `lastboottimeat`, `parentninjaid`, `platformgroupid`,
  `entitytype`, `devicerole`. Was over-fitting the raw shape; now
  matches canonical shape.

### Changed
- Section titles under Identity & raw: "Common fields across sources"
  → "**Fields**" and "Per-source details" → "**Source-native
  fields**". Copy tightened to describe the new canonical-first model.

## [0.81.0] — 2026-07-22 — Observation writer hardening + retention wired (ADR-0007 v5)

### Fixed
- **Absent-row race in `ingest/observations.py::write_current_rows`.**
  `SELECT ... FOR UPDATE` alone cannot lock a row that does not exist
  yet, so two concurrent writers claiming the same new identity could
  both open a history version. The primitive now takes a
  transaction-scoped `pg_advisory_xact_lock(hashtextextended(...))`
  keyed on the 5-column identity tuple before the FOR UPDATE read.
  Batches are pre-sorted by identity to prevent deadlocks between
  concurrent writers that share some — but not all — identities.
- **Out-of-order snapshot could overwrite newer `_current` state.** The
  previous `db.upsert` path wrote `EXCLUDED.c` on every column with no
  timestamp predicate. Delayed workers or clock-skewed sources could
  poison newer state and open a phantom SCD-2 interval. The primitive
  now drops rows in Python when `row.observed_at <= _current.observed_at`
  (equal timestamps treated as stale to prevent zero-length intervals),
  and the bespoke SQL upsert mirrors the guard as defense in depth:
  `WHERE _current.observed_at < EXCLUDED.observed_at`.
- **Connector NULL could clear resolver-populated `device_id`/`client_id`.**
  Bespoke upsert now uses
  `COALESCE(EXCLUDED.client_id, entity_observation_current.client_id)`
  (and same for `device_id`), so post-hoc resolver and merge writes are
  preserved. Python-side merge runs too, before shaping.
- **`_history` close attributed the closing time to the new state.**
  `write_history_changes` now closes with `_prior_last_seen_at`
  (side-banded from the current row's prior `last_seen_at`), not the
  incoming row's `last_seen_at`. The new state's `last_seen_at` is
  correctly the new observation's confirmation time.

### Added
- **Nightly closed-history retention scheduler.** `ingest/main.py::
  run_observation_history_prune_once` calls
  `retention_observations.purge_all()`, which delegates to the
  security-definer function `operations.purge_closed_observation_history(
  cutoff)` (migration 0074). Default 90 days; overridable via
  `OBSERVATION_HISTORY_RETENTION_DAYS` and
  `OBSERVATION_HISTORY_RETENTION_HOUR`. Covers both
  `entity_observation_history` and `software_installation_history`.
  Cannot delete open SCD-2 versions (function DELETE is scoped to
  `effective_to IS NOT NULL`).
- Focused tests: 7 new hardening tests in
  `ingest/tests/test_observations.py` (out-of-order older, equal-
  timestamp, resolved-ID preservation, material-change with prior
  last_seen_at, heartbeat without material change, new identity opens
  first history version, batch sorted by identity before locking). New
  `ingest/tests/test_retention_observations.py` asserts retention
  routes through the security-definer function and never issues raw
  DELETE from application code.

### Changed
- `ingest/core/devices.py` and `ingest/source_observations.py` now
  record the actual return count from `write_current_rows` on the
  snapshot run ledger (`operations.observation_snapshot_runs`) instead
  of the input length, so skipped out-of-order rows are not counted as
  written. Cosmetic accuracy improvement to the run log.

## [0.80.0] — 2026-07-21 — Raw tab: common-field matrix + category grouping + Ninja fallback

### Added
- **Common-fields matrix on the Identity & raw tab.** Fields that
  appear in ≥2 source snapshots roll up into a top card, grouped
  by category (Identity / Serial & IDs / Network / Operating
  system / Hardware / Presence & state / Enrollment & grouping /
  Other). Each row shows the value(s) with source attribution:
  agreement collapses to one line; disagreement renders one line
  per distinct value with which sources report it, and the row
  gets an amber highlight + ⚠ prefix so cross-source conflicts
  jump out visually. Category matching is case-insensitive and
  strips `_`/`-` so `is_online` and `isOnline` bucket together.
- **Per-source details card** replaces the previous per-source
  raw-JSON blocks. Each source's `<details>` opens to (a) a table
  of fields unique to that source, and (b) a nested `<details>`
  for the full raw JSON payload — the noisy long-tail is one
  extra click away, not the default view.
- **Ninja read-side fallback.** When a Ninja `agent.rmm`
  observation writes an empty `raw_data` (upstream ingest gap,
  tracked as a follow-up), the view swaps in
  `ninja_core.devices.data` for the device's Ninja external_id.
  The section shows an "ⓘ from ninja_core.devices (raw
  observation was empty)" note so operators know it's a fallback.

## [0.79.0] — 2026-07-21 — Device Detail: exemptions, Raw tab, Ninja activity feed

### Added
- **Ninja activity feed on the Device Activity tab.** Reads the
  last 100 events from `ninja_activities.activities` for the
  device's Ninja `external_id` and merges them into the existing
  timeline (issue events + boot + patch). Devices without a Ninja
  link silently fall back to the previous timeline. New migration
  `0062_grant_ninja_activities_select` grants Operations roles
  `USAGE`/`SELECT` on the `ninja_activities` schema (mirrors 0059's
  `ninja_patches` grant). Starter mapping of Ninja `activity_type`
  strings (`PATCH_MANAGEMENT_APPLY_PATCH_COMPLETED` etc.) added to
  `human_labels.py` for readable rendering.
- **Raw source snapshots on the Identity & raw tab.** Replaced the
  placeholder note with per-source collapsible sections showing
  the most recent `entity_observations.raw_data` payload per
  (platform, entity_type). Query runs only when the tab is active
  to keep other tabs fast.
- **Persistent exempt badge** in the device header meta line —
  visible from every tab, tooltip lists reason per requirement.
  Answers "where can I see this device is S1 exempt?" without
  scrolling to the Coverage exemptions card.

### Changed
- **Exemption chips now read "Exempt from EDR — [reason]"** instead
  of the awkward "EDR agent — [reason]". New `humanize_exemption`
  filter renders entity-type keys as the requirement they exempt
  from (`agent.edr` → "EDR", `agent.remote_access` → "Remote
  access", etc.) rather than the agent noun. Add-exemption
  dropdown uses the same filter for consistency.

## [0.78.0] — 2026-07-21 — Sanctioned fuzzy-match + single Admin nav

### Fixed
- **Required agents no longer flagged as `unauthorized_*`.** The
  sanctioned-set membership check in
  `ingest/software_findings.py` compared Agent product names
  (e.g. `"LogMeIn"`) against software canonical_names
  (e.g. `"logmein client"`) as exact strings — they rarely line up.
  New `_matches_sanctioned` helper does case-insensitive substring
  match either direction: agent name in canonical, or canonical in
  agent name. Handles LogMeIn / Ninja / ScreenConnect reliably;
  edge cases (SentinelOne → `sentinelagent`) get their own mapping
  if the pattern turns out to matter.

### Changed
- **Nav collapsed to a single `Admin` entry** at the right end of
  the primary row. Row 2 (Review / Config / Integrations) removed;
  those surfaces are still reachable via the existing
  `_admin_tabs.html` strip on any admin page. `Admin` link lands on
  the Review queue by default (`client_candidates_queue`). Django
  admin ⚙ still to the far right.

## [0.77.3] — 2026-07-21 — Fix: comment leak on Config page + Detail/Subject cleanup

### Fixed
- Multi-line `{# ... #}` comment leaked on every Config / Review /
  Integrations page — `_admin_tabs.html` had a five-line block.
  Django single-line inline comments require closing `#}` on the
  same line; the block rendered as page text. Replaced with
  `{% comment %} ... {% endcomment %}`.
- Findings queue "Subject" column renamed to "Device" — 99% of
  findings target a device; the type-agnostic "Subject" label was
  confusing. Non-device rows still render via fallback in the cell.
- Findings queue Detail column now uses `finding_detail_text`
  template tag — previously used the view-computed `row.detail`
  which only knew coverage/patching types, so every software
  finding rendered as "—". Tag has broader coverage: unauthorized
  AV/RMM/remote-access, suspicious_name, install_path_suspicious,
  eol_runtime, multi_av_conflict, rare_recent + all data-quality
  types.
- `_detail_string()` in `findings_queue` view extended to match the
  tag's software-finding coverage so CSV export matches the on-
  screen row.

## [0.77.2] — 2026-07-21 — Fix: 500 on Issues queue with software findings

### Fixed
The 0.77.1 template used
`{% with device_name=row.subject_hostname|default:f.finding_details.hostname %}`.
Django evaluates the `|default` argument eagerly and raises
`VariableDoesNotExist` when a dict lookup misses — which happens
for every software finding
(`finding_details = {reason, category, publisher, canonical_name}`,
no `hostname` key). Every Issues queue page load with a software
finding on it 500ed.

Fix computes the fallback in the view (`_subject_display_name`
helper picks `hostname_by_device_id.get(subject_id)` first, then
`finding_details.hostname`, else `None`). Template just uses
`row.subject_hostname` with a plain-string default. No more dict
lookups in the template.

## [0.77.1] — 2026-07-21 — Fix: Subject column shows real hostname + comment leak

### Fixed
- **Broken multi-line `{# ... #}` comment leaked into the Issues
  queue Subject column**, rendering "Always link the device even
  when hostname isn't in..." as visible page text. Django's inline
  comment syntax is single-line only; multi-line requires
  `{% comment %}...{% endcomment %}`. Comment removed outright —
  the code is self-explanatory now.
- **Subject column now shows the actual device hostname** for
  every device-subject finding, not a UUID snippet. Software
  findings (`unauthorized_av / _rmm / _remote_access`,
  `suspicious_name`, etc.) don't carry `hostname` in
  `finding_details`, which was leaving the column falling back to
  8-char UUID. `findings_queue` view now bulk-fetches
  `canonical_hostname` for every device-subject on the page in
  one query, exposed as `row.subject_hostname` in the template.
- **Subject column visual cleanup**: dropped the redundant "Device"
  type label above every device row. Client-subject findings link
  to the client detail. Non-device / no-hostname cases fall back
  to the type label as a muted line.
- CSV export "Hostname" column now uses the bulk-fetched name too.

## [0.77.0] — 2026-07-21 — Re-enable legacy AC scheduler (bridge)

### Why
Legacy `ingest/agent_compliance/` was removed from the auto-run
schedule during cutover to Operations, leaving `ninja_agent_compliance.*`
tables stale and the AC Metabase dashboards frozen. Operators need
the AC surface alive a while longer while they transition. Legacy
AC uses its own platform fetchers (Ninja / S1 / LMI / SC) — not
Operations data — so re-enabling means the module simply resumes
its own ingest cycle.

### Changed
- `ingest/main.py` scheduler now includes two AC jobs:
  - `agent_compliance_ingest_cycle` — `run_agent_compliance_once`
    every `AGENT_COMPLIANCE_SCHEDULE_HOURS` (default 4h).
  - `agent_compliance_evaluate_cycle` — `run_agent_compliance_evaluate_once`
    on the same cadence.
- Both jobs are internally gated by `settings.AGENT_COMPLIANCE_ENABLED`
  (default `False`). Scheduling them is safe when the flag is off —
  each fires and no-ops. Set `AGENT_COMPLIANCE_ENABLED=True` in the
  deploy env to actually run them.
- Comment above the jobs marks this as a bridge, not a permanent
  arrangement — the legacy module still calls the platform APIs
  directly (duplicating some ingest that Operations already does).
  Retire when operators are off the AC dashboards.

## [0.76.1] — 2026-07-21 — Fix: software finding detail + Subject column always links

### Fixed
- `finding_detail_text` template tag now covers software findings:
  `unauthorized_av / _rmm / _remote_access`, `suspicious_name`,
  `install_path_suspicious`, `eol_runtime`, `multi_av_conflict`, and
  `rare_recent`. Previously showed "—" (no detail) because the tag
  had no branch for these types. Detail now renders as
  `canonical_name (publisher) @ location` for the unauthorized/
  suspicious/EOL types; comma-list of AVs for multi_av_conflict;
  `canonical · on N machines · first seen Xd ago` for rare_recent.
- Findings queue Subject column always renders a `device_detail`
  link when `subject_type='device'` and a client is present, even
  when `finding_details.hostname` isn't set (software findings
  don't include hostname). Text falls back to the first 8 chars of
  `subject_id` if hostname is missing, so the row is never a bare
  "device" label with no click-through.

## [0.76.0] — 2026-07-21 — Nav rework + detail column + location truncate

### Why
Three UX fixes:

1. Top nav had a wide empty gap between operator and admin clusters,
   admin text was undersized and heavily muted.
2. Software install-location column overflowed the page on long paths.
3. Device Detail Issues tab showed the finding type but no context
   ("Required agent not installed" with no hint which agent, no
   click-through to see the full history of that issue on this
   device).

### Changed
- **Two-row primary nav.** Row 1 = operator workflow at 0.95rem,
  brighter (#cbd5e1). Row 2 = admin cluster (Review / Config /
  Integrations / ⚙) at 0.86rem on a slightly darker band. No more
  fill-gap. Client sub-nav stays inline on row 1 when a client is
  scoped.
- **Location column ellipsis + tooltip.** New `.trunc-160 /
  -240 / -320` utility classes in `base.html` for reuse. Applied
  to `org_software.html` (per-title locations list) and
  `org_software_devices.html` (per-device install path) — first ~80
  chars shown with `title` giving the full multi-line list on hover.
- **Device Detail Issues tab detail column.** Each row now shows a
  compact per-type detail via new `finding_detail_text` template tag
  (unified with the `_detail_string` logic from findings_queue).
  Coverage: platform for missing/stale, offline-since for
  device_offline, KB counts for patch_failing_repeatedly, machine
  count for rare_recent, plus all data-quality finding types.
- **Click-through from Issues label → filtered findings queue.**
  Clicking the issue label goes to
  `/findings/?type={name}&subject_id={device_id}&status=all` —
  full history of that finding type on this specific device across
  every status.
- **New `subject_id` filter on `findings_queue`.** Powers the
  click-through above; also usable directly (`?subject_id=<uuid>`)
  for anything targeting a specific subject. UUID-validated;
  invalid values silently ignored.

## [0.75.2] — 2026-07-21 — Emergency: fast-path entity_type guard + cleanup

### Why
Two bugs in 0.75.1's fast-path fix, discovered when migration 0060
crashed on production with
`UniqueViolation: (1, 1, 'microsoft edge')`:

1. `_upsert_link_for_fast_match` didn't check entity_type. Software
   observations (`entity_type='software'`) use `entity_key` = software
   name (e.g., `'microsoft edge'`), shared across many devices. Since
   0.75.1 deploy, every software observation hitting fast_path step
   2/3 was upserting a synthetic device_link keyed on the software
   name, reassigning it between devices in-place via `ON CONFLICT
   DO UPDATE`.
2. Migration 0060's backfill had the same missing filter — it tried
   to insert one device_link per (device, software) tuple, all
   sharing `(source, external_id='microsoft edge')`, violating the
   unique constraint on the first collision.

### Fixed
- `_is_identity_signal(entity_type)` gate in
  `ingest/identity/fast_path.py` — only creates device_links for
  entity types that are per-device identity signals:
  `agent.*` + `vm.host` + `vm.guest` + `network.device` +
  `monitor.target`. Software (and any other per-installation record)
  gets its device_id set on the observation with no link, matching
  pre-0.75.1 behavior for those types while still fixing the agent
  gap.
- Migration `0060` rewritten:
  - **Cleanup step** removes any bogus `device_links` created by the
    0.75.1 fast_path bug (`external_id` matches a software
    `entity_key` in `entity_observations`) plus any prior
    `fast_path_backfill` rows.
  - **Backfill step** now filters `entity_type` to identity signals
    only and uses `ON CONFLICT DO NOTHING` as a safety net.
  - Both operations run in one migration → all-or-nothing.
  - Idempotent — safe to re-run.

### Impact
- Any existing device attribution done through the corrupted
  device_links since 0.75.1 deploy will re-resolve correctly on the
  next fast_path or resolver pass — device_link is a display /
  identity cache, not the source of truth for observation ↔ device
  linkage (which is `entity_observations.device_id`).
- No schema change; only data cleanup + code guard.

## [0.75.1] — 2026-07-21 — Fix: fast-path device_link gap

### Fixed
- `ingest/identity/fast_path.py::resolve_device_fast` was returning
  a matched device_id (via serial or hostname) without creating the
  corresponding `device_link` row. Only step 1 (existing link) had
  a link; steps 2 (serial) and 3 (hostname) skipped it. Result:
  `entity_observations` had `device_id` set and derived matviews
  showed the source on the device, but the `device_links` table
  was missing the row entirely — visible on Device Detail as
  "presence but no source identity."
  - Field example: cl-15 in Chartwell Pharma had SentinelOne
    presence + no SentinelOne source identity.
  - Fleet-wide impact at time of fix: 21 devices.
- Fix upserts the link at match time via
  `_upsert_link_for_fast_match` — same ON CONFLICT semantics as the
  polling resolver's `_attach_observation`.
- Migration 0060 backfills the existing gap by deriving missing
  `device_links` from `entity_observations`. Backfilled rows are
  identified by `match_method='fast_path_backfill'`.

## [0.75.0] — 2026-07-21 — Finding label with platform + offline-agent visibility

### Why
Two operator-visibility fixes to how coverage findings appear:

1. Device-detail Issues tab labeled every
   `missing_required_platform` finding as the generic "Required
   agent not installed" — operators had to click into the row to
   see *which* agent.
2. `stale_required_platform` findings were suppressed entirely when
   the whole device was fully offline (per BLUEPRINT §1.8's
   noise-reduction rule). Operators still wanted to see which agent
   was missing on an offline device; the current behavior hid
   information they needed.

### Changed
- **`finding_display_label` template tag** in `human_labels.py`.
  Composed label = humanized FindingType name + `: {platform}` for
  missing/stale-required findings + `(device offline)` suffix when
  the evaluator marked the finding as offline-downgraded. Wired into
  `device_detail.html`, `findings_queue.html`, `patching_queue.html`,
  `home.html` — every place the finding row label renders.
- **Evaluator** (`ingest/evaluator.py`) no longer skips
  `stale_required_platform` on fully-offline devices. Instead:
  demotes severity to `info` for both `stale_required_platform`
  and `missing_required_platform` when the device is fully offline,
  and marks `finding_details.reason_suppressed='device_offline'`.
  Result: both findings visible in Issues + on Device Detail,
  clearly labeled as offline-context, without dominating the
  default active-severity queue view.

### Impact
- Findings queue default (active status) shows offline-downgraded
  rows only when filtering to include `info` severity. Default
  severity filter (critical / high / medium) continues to skip
  them → no visible noise increase on the operator's daily view.
- Device Detail Issues tab shows every applicable finding at any
  severity, so offline devices now correctly display both their
  device_offline status and the specific agent gaps that persist.

## [0.74.1] — 2026-07-20 — Fix: patch page 500s + sortable rollout

### Fixed
- **500 on device_detail + patching pages** — Operations app roles
  had no SELECT on the `ninja_patches` schema, which multiple views
  join (device_detail's patch-signal, the 0.73/0.74 Patch Evidence
  / Trends / Activity Search pages). Migration 0059 grants
  USAGE + SELECT on the schema to `operations_app`,
  `operations_readonly`, and `metabase_ro`, plus default privileges
  so future tables auto-inherit.
- **Every table now has `data-sortable`** — per the UI/UX ground
  rule "every table sortable+filterable". 8 templates had `<table>`
  elements without the attribute (missed on initial creation or in
  the CSV rollout when I was already in the file):
  client_candidate_detail, findings_admin_health,
  merge_candidates_queue, notification_suppressions, org_policies,
  patching_queue (2 tables), requirement_profiles, search_results.
  Every list-view table across the app is now sortable via the
  existing `table[data-sortable]` header-click JS in `base.html`.

## [0.74.0] — 2026-07-20 — Patch Trends + Activity Search

### Why
Slice B and C of the patching-visibility track. Closes the two
remaining Metabase patching-dashboard GAPs (Patch Trends, Activity
Search). All data was already in `ninja_patches.patch_facts`
(`fact_type='install_outcome'`); no ingest changes needed.

### Added
- `GET /patching/trends/` — `patch_trends_page` view. Per-day
  install / failure counts + failure percentage + devices touched
  over a configurable window (7/14/30/60/90/180 days, default 30).
  Optional client filter. Overview tiles + a stacked-bar column
  showing install vs failure volume per row. CSV export.
- `GET /patching/activity/` — `patch_activity_search_page` view.
  Free-text search across recent patch install outcomes with
  filters for patch name / KB, status, client, and time window.
  Newest-first, capped at 500 events per query. CSV export.
- Nav links between all three patching pages
  (queue ↔ evidence ↔ trends ↔ activity).

### Follow-up
- The patching-visibility track (per the legacy-scripts audit and
  the Metabase parity audit) is now closed at Operations parity for
  the three named GAPs (Patch Evidence, Trends, Activity Search).
  The corresponding Metabase dashboards can be retired when
  operators have moved over.

## [0.73.0] — 2026-07-20 — Fleet Patch Evidence

### Why
First slice of the patching-visibility track. Closes both a
Metabase-dashboard GAP (Patch Evidence) and the legacy
`Ninja-Patching-report.ps1` script's intent in one Operations
surface. All patch data was already in the pipeline
(`ninja_patches.current_patch_state` +
`ninja_patches.latest_install_outcome`); no ingest changes needed.

### Added
- `GET /patching/evidence/` — `patch_evidence_page` view. Renders
  one row per (device, patch) with current state, joined to
  device / client metadata and the latest install outcome.
- Server-side filters: status (Installed / Failed / Pending /
  Approved / Rejected / Manual / Delayed), severity (Critical /
  Important / Moderate / Low / Optional / Unspecified), client,
  free-text search over patch name and KB number.
- Fleet-wide status tiles (counts per status across the whole
  fleet, ignoring active filters).
- CSV export via the standard `?format=csv` — 13 columns
  including install-outcome status/date for each row.
- Row cap 1000 for the table view (CSV export capped at the same
  underlying query for now — bumping is trivial when needed).
- "Patch Evidence →" link added to the patching-queue header for
  operator discovery.

### Not in this slice
- Patch Trends (per-day install/failure/reboot volumes).
- Activity Search (free-text search over patch activity events).
Both follow in subsequent versions.

## [0.72.1] — 2026-07-20 — Reclassify data-quality findings as entity

### Fixed
`unmatched_source_group` (0.70.0) and `unnamed_source_group` (0.72.0)
were seeded with `finding_class='admin'`, but per DESIGN §6.1 the
admin class is reserved for findings about the Operations tool's
own health (connector down, queue stalled, matview stale, etc.).

Both are actually about data quality on source records — operations
findings, not admin. The emitter already writes them to
`operations.findings` (correct for entity class). Migration 0058
just aligns the `finding_class` in the registry with where the rows
already live. No data migration; no emitter change.

## [0.72.0] — 2026-07-20 — Close nothing-hidden audit gaps

### Why
Follow-through on `operations/docs/nothing-hidden-audit.md`. Two
remaining silent filters that 0.70.0 didn't cover:

- `ingest/normalize.py::_JUNK_MACS` — junk MACs (all-zero, all-FF,
  VirtualBox default NAT) silently disregarded from identity
  correlation.
- `ingest/identity/client_resolver.py:104` — empty-name source
  groups (e.g. LMI "-1" placeholders) silently skipped before
  reaching the `unmatched_source_group` path.

Both now surface as standard `operations.findings` rows.

### Added
- FindingType seeds (migration 0057):
  - `placeholder_mac` — severity medium, category identity,
    auto_resolvable. Subject: the affected device. `finding_details`
    lists the junk MACs found.
  - `unnamed_source_group` — severity low, class admin, category
    identity, auto_resolvable. Subject: source_binding.
    `finding_details` includes source_binding_id + entity_key +
    platform + source_id.
- `_sync_device_attributes` in `ingest/identity/resolver.py` sweeps
  observations from the last 30 days for any junk MAC and upserts
  one `placeholder_mac` finding per affected device. Idempotent via
  ON CONFLICT.
- `_emit_unnamed_source_group_finding` in
  `ingest/identity/client_resolver.py` wired at the empty-name skip
  site. Writes directly to `operations.findings` (standard table),
  not the legacy `admin_findings` side table.

### Notes
- Both new findings are `auto_resolvable=True` — auto-close when the
  underlying condition disappears.
- Correctness gates unchanged; only visibility added.
- Audit doc remains authoritative. One deferred concern
  (per-exclude-entry drop counts on `placeholder_org_names` /
  `org_excludes`) plus a newly-observed sibling issue
  (`admin_findings` is another per-type side table that should be
  consolidated into `operations.findings`) are backlogged.

## [0.71.1] — 2026-07-20 — Complete CSV export rollout

### Added
CSV export on every remaining list-view table, using the same
`csv_response` helper + `_csv_download.html` include shipped in
0.71.0:

- **Admin queues:** Merge candidates, Client candidates, Software
  decisions, Requirement profiles, Notification rules,
  Notification suppressions.
- **Operational surfaces:** Patching queue, Fleet coverage
  compliance gaps, Sources status.
- **Per-client:** org_devices, org_software, org_software_devices.

Each view accepts `?format=csv` on its existing filtered URL and
returns a timestamped attachment matching the current view.

## [0.71.0] — 2026-07-20 — CSV export helper + first three tables

### Why
Per the "every table should be exportable" rule (2026-07-20). Operators
were browser-only for viewing tables; no way to pull a filtered view
into a spreadsheet for offline review or handoff.

### Added
- `operations/apps/core/csv_export.py` — reusable helper. Any list
  view can opt in by calling `csv_response(rows, columns, filename)`
  when `wants_csv(request)` is True. Column declaration is
  `(header_label, key_or_getter)` tuples; getter can be a string
  field/dict key or a callable. Writes UTF-8-BOM CSV so Excel opens
  cleanly with non-ASCII characters; filename is timestamped.
- `operations/templates/_csv_download.html` — reusable include. Renders
  a "⤓ CSV" link that preserves the current query string so the
  exported CSV matches whatever filtered view the operator is on.
- `a.csv-download` styling added to `base.html`.
- Wired into three highest-traffic list views:
  - `findings_queue` (`/findings/`) — 16 columns including severity,
    type, category, client, hostname, detail, online sources,
    status, confidence, timestamps.
  - `devices_page` (`/devices/`) — hostname, client, serial, role,
    OS group, OS name, online, sources, last contact, patch scope,
    severe issues count, device ID.
  - `software_page` (`/software/`) — canonical name, publisher,
    device count, client count, last install, categories, decision.

### Follow-up
- Remaining tables (Software decisions queue, Client detail
  scoreboard tables, Device detail tabs, admin queues, patching
  views) get the same treatment — mechanical work per view. Track
  as a follow-up slice.

## [0.70.0] — 2026-07-20 — Surface silent data-quality filters as Findings

### Why
Per the "nothing hidden or silently ignored" rule
(`memory/feedback_nothing_hidden.md`, 2026-07-20). Three ingest-side
silent filters used to hide their inputs from the operator:

- `is_usable_serial()` correctly skips placeholder serials for
  identity matching — but the affected devices were invisible.
- Devices sharing a canonical_serial were only surfaced on the
  retired identity_candidates_list page.
- Rows in `operations.unmatched_source_groups` were visible only in
  ingest logs (or as an aggregate count on the retired page).

All three now emit standard `operations.findings` rows through the
resolver's attribute-sync sweep — same table, same lifecycle, same
queue as every other finding (per the "findings live in one table"
rule).

### Added
- FindingType seeds (migration 0056):
  - `placeholder_serial` — severity high, category identity,
    auto_resolvable. Subject: the affected device.
  - `shared_serial` — severity high, category identity,
    auto_resolvable. One finding per (client, serial) with all
    sharing device IDs + hostnames in `finding_details`.
  - `unmatched_source_group` — severity medium, class admin,
    category identity, auto_resolvable. One finding per pending row
    in `operations.unmatched_source_groups`.
- Three SQL emit blocks appended to
  `_sync_device_attributes` in `ingest/identity/resolver.py`. Each
  is idempotent via `ON CONFLICT (tenant, condition_key) DO UPDATE`
  on the standard partial unique index; repeat drains refresh
  `last_seen_at`/`last_detected_at` without duplicating.

### Notes
- All three are `auto_resolvable=True` — once the underlying
  condition disappears (serial corrected, duplicate merged, source
  group resolved) the next sweep leaves the Finding stale and the
  finding-close pass closes it.
- The resolver's `is_usable_serial()` correctness behavior is
  unchanged — placeholder serials still don't drive identity
  matches. This release only surfaces the previously-invisible set.

## [0.69.0] — 2026-07-20 — Layer-entity field-history audit triggers

### Why
The `asset_field_history`, `os_instance_field_history`, and
`agent_instance_field_history` audit tables were scaffolded in
ADR-0005 slice 1 (migration 0050) but never wired. Under ADR-0006's
attribute-bucket model, these audit trails *are* the history mechanism
— per-layer trends and forensics query them, not any lifecycle
window. This release activates them.

### Added
- `operations.audit_asset_significant_fields()` +
  `audit_asset_fields` trigger — AFTER UPDATE on `operations.assets`,
  fires only when a significant field changed
  (form_factor, serial, vm_uuid, chassis). Emits one audit row per
  changed field.
- `operations.audit_os_instance_significant_fields()` +
  `audit_os_instance_fields` trigger — AFTER UPDATE on
  `operations.os_instances`. Fields: os_name, os_family, os_group,
  os_version.
- `operations.audit_agent_instance_significant_fields()` +
  `audit_agent_instance_fields` trigger — AFTER UPDATE on
  `operations.agent_instances`. Field: agent_version.
- Migration 0055.

### Notes
- Heartbeat / last_seen / timestamp columns are explicitly excluded
  from audit — WHEN clause on each trigger filters to significant
  fields only.
- JSON state blobs (virtualization, patch_state, config_state,
  coverage_state) are not audited in v1 — diff semantics too noisy.
  Can be added later at operator-visible granularity.
- Change context is `change_reason='trigger.audit'` and
  `change_source_id=NULL`. Richer context (per-writer source binding,
  transaction reason) would require SET LOCAL plumbing from every
  writer; deferred.

## [0.68.0] — 2026-07-20 — Retire identity_candidates (side-table consolidation)

### Why
`operations.identity_candidates` was the last remaining per-finding-type
side table with its own admin surface and workflow. Per the "findings
live in the standard table — no side tables per type" rule, the
identity-conflict operator surface is the standard findings queue
filtered on `identity_conflict`, and the merge action is the generic
`device_merge` view on the Devices surface (both landed in 0.66.x /
0.67.0). This release removes the legacy surface and drops the table.

### Removed
- `identity_candidates_list` view + `identity_candidate_confirm` +
  `identity_candidate_reject` handlers in `operations/apps/core/views.py`.
- URL routes `admin/identity/`, `admin/identity/<uuid>/confirm`,
  `admin/identity/<uuid>/reject` in `operations/config/urls.py`.
- Nav tile "Identity matches" from `home.html`.
- `Devices` tab from the Review admin strip in `_admin_tabs.html`
  (formerly linked to the retired page). The Devices layer of Review
  now surfaces via the standard findings queue with a
  `finding_type=identity_conflict` filter.
- `nav_pending_identity_candidates` from the base context processor.
- `reviews_pending['identity_candidates']` from the home view.
- `IdentityCandidate` Django model.
- `INSERT INTO operations.identity_candidates` block in
  `ingest/identity/resolver.py::_maybe_create_candidate` — the resolver
  now only emits standard `identity_conflict` Findings.
- `operations/templates/identity_review.html`.

### Database
- Migration 0054 drops `operations.identity_candidates` (RLS policy +
  table, via `SeparateDatabaseAndState` so Django model state
  synchronizes). 12 pending rows existed at retirement time; any live
  hostname conflict they represented will be re-detected on the next
  resolver drain and re-emitted as an `identity_conflict` Finding.
  Historic confirm/reject decisions from the retired admin page remain
  in `operations.audit_log`.
- `_merge_devices` helper stays as the shared merge cascade — now
  called only by the new `device_merge` view (0.67.0).

## [0.67.0] — 2026-07-20 — Generic device-merge action

### Why
Merging two Devices was previously only reachable through the
`identity_candidates_list` admin page — a per-finding-type ecosystem
that violated the "findings live in the standard table, no side tables
per type" rule. The merge is a **generic entity operation** that
belongs on the Devices surface and is invokable from any context that
has two Device IDs (including future device-detail actions and any
Finding evidence with candidate references).

This ships the merge as a first-class device operation. Retirement of
the legacy `identity_candidates` page + table follows in the next
slice, which is why the legacy page still works alongside this
release.

### Added
- `POST/GET /orgs/<org_slug>/devices/<uuid:device_id>/merge/<uuid:target_id>/`
  — `device_merge` view (`operations/apps/core/views.py`). GET renders
  a side-by-side confirmation page with a survivor radio selector
  (default suggests Ninja-linked device, else older by created_at).
  POST executes the merge via the existing `_merge_devices` helper,
  audits the action, flashes a summary, and redirects to the
  survivor's detail page. Cross-client merges rejected.
- `operations/templates/device_merge.html` — the confirmation
  template. Side-by-side card layout, survivor radio, source badges,
  destructive-but-reversible warning, cancel link.
- Findings-queue row enrichment for `identity_conflict` findings:
  when `candidate_count == 2`, a "Merge candidates →" link is shown
  under the hostname, wired to the `device_merge` URL with the two
  candidate IDs.

### Not yet
- Device-detail entry point ("Merge with…") requires a target-picker
  UI — deferred.
- `identity_candidates` page + table retirement follows in the next
  release.

## [0.66.1] — 2026-07-20 — identity_conflict correctness bundle

### Fixed
- `_maybe_create_candidate` — ON CONFLICT WHERE clause now matches the
  Finding partial unique index predicate verbatim (`condition_key > ''`
  instead of `<> ''`). Postgres matches ON CONFLICT to partial indexes
  by expression AST, not semantic equivalence; without this fix the
  first `identity_conflict` emit would have raised "no unique or
  exclusion constraint matching the ON CONFLICT specification." Bug was
  latent — no `identity_conflict` findings had fired against prod yet.

### Changed
- `identity_conflict` FindingType flipped to `auto_resolvable=True`
  (migration 0053). Resolution acts on the underlying Devices (merge,
  retire, rename) as an entity operation; once the hostname collision
  disappears, the finding auto-closes on the next resolver drain.
  Matches the entity-action + auto-close pattern used elsewhere.

## [0.66.0] — 2026-07-20 — identity_conflict Finding on hostname-only conflicts

### Why
ADR-0005 slice 3. When the resolver finds two or more Devices sharing a
hostname in the same client with no strong corroborating identifier
(serial / vm_uuid / MAC / install token), hostname alone never merges.
Previously the conflict was recorded only in the
`operations.identity_candidates` side table and its dedicated admin UI;
operators triaging via the standard findings queue never saw it.

Per the "findings live in the standard table — no side tables per type"
rule, ambiguous identity conflicts now emit a standard
`identity_conflict` Finding into `operations.findings` with severity
`high`, deduplicated by `condition_key='identity_conflict:{hostname}'`.
The Finding's evidence panel carries the candidate device IDs, hostname,
and trigger observation.

### Added
- `operations.finding_types` seed: `identity_conflict` (severity `high`,
  class `entity`, category `identity`, not auto-resolvable).
- `_maybe_create_candidate` now emits an `identity_conflict` Finding
  alongside the legacy `identity_candidates` write (dual-write during
  transition — the legacy admin UI has live consumers). Uses
  `ON CONFLICT ... DO UPDATE` on the partial unique index over
  `(tenant, condition_key)` for active statuses so repeat observations
  refresh the same open Finding rather than piling up duplicates.
- Migration 0052.

### Deferred
- Retirement of `operations.identity_candidates` — the table has live
  UI consumers (admin page, home dashboard, URL route). Migrating them
  to the standard findings queue filtered on
  `finding_type='identity_conflict'` is a bounded destructive track,
  tracked in `operations/.work/backlog.md`.
- Audit of other finding-like side tables (`merge_candidates`, etc.)
  for the same consolidation.

## [0.65.0] — 2026-07-20 — Layered entity writes at resolution + form-factor rule fix

### Why
ADR-0005 slice 2. With the layer entity tables and open-window backfill
in place (0.64.0), the ingest identity resolver now writes to them
directly: every promoted Device gets an open-window `Asset` row and,
for OS-carrying kinds, an open-window `OSInstance` row. The attribute
sync step propagates further changes to those layer rows so they stay
consistent with the flat `Device` cache columns. Slice 2 also fixes
the form-factor inference bug the ADR named: agent presence is no
longer evidence of physical hardware.

### Changed
- `ingest/identity/resolver.py::_infer_form_factor` — dropped the
  `agent → physical` fallback. Form factor now stays `unknown` in the
  absence of asset-nature evidence (network.device / vm.host /
  vm.guest / is_vm flag). Same rule reflected in the
  `_sync_device_attributes` SQL.
- `_promote_unmatched_clusters` and `_promote_entry_groups` now open
  `assets` (asset_type='endpoint_hardware') and, conditionally,
  `os_instances` rows alongside every new `devices` insert. Uses the
  partial unique indexes' `ON CONFLICT DO NOTHING` to stay idempotent
  under concurrent drains.
- `_sync_device_attributes` gained layer-propagation SQL: updates
  `assets.form_factor` when the flat Device cache changes, opens
  missing `os_instances` for Devices that now carry an `os_name`,
  syncs OS fields on the current OSInstance window, and opens missing
  `agent_instances` rows for any (Device, Agent product) with
  agent-nature observations that don't yet have an open window.
- `_write_layer_entities_for_new_device` extended to also emit
  `agent_instances` rows for `entity_type LIKE 'agent.%'` entries at
  Device promotion, mapping observation `platform` to the seeded
  `operations.agents` product (Ninja / SentinelOne / LogMeIn /
  ScreenConnect). `install_token` / `agent_version` fields are
  populated when present in the observation's canonical_data.
- `_promote_entry_groups` signature gained an `agent_ids` parameter;
  callers in `_promote_unmatched_clusters` pass it through.
- `_load_agent_ids` helper added alongside `_load_source_ids`.

### Not yet
- Identity-conflict finding on hostname-only matches remains deferred
  pending a decision on how it coexists with the existing
  `identity_candidates` operator-review table (see plan).

## [0.64.0] — 2026-07-20 — Device layered entities (schema + backfill)

### Why
ADR-0005 (`operations/docs/decisions/0005-device-identity-and-layered-entities.md`)
splits the current chimeric `Device` model into an identity anchor plus
first-class layer entities (`Asset`, `OSInstance`, `AgentInstance`) with
their own effective windows and lifecycles. Slice 1 lands the schema
and backfills current state as open-window rows. The existing collapsed
`v_device` surface is unchanged; flat `Device` attribute columns stay
as a denormalized cache. `Asset` is scoped broadly (asset_type field)
to accommodate the MSP-platform vision (peripherals, licenses, network
appliances) without paying that cost in v1 — only endpoint_hardware is
populated by the backfill.

### Added
- `operations.assets` — tenant-scoped, effective-windowed. Fields:
  `asset_type` (endpoint_hardware / peripheral / network_appliance /
  license / service / other), `form_factor`, `serial`, `vm_uuid`,
  `chassis`, `virtualization`. Nullable `device` FK (accessories and
  standalone-inventory assets don't require a Device). Partial unique
  index enforces at-most-one open endpoint_hardware asset per Device.
- `operations.os_instances` — one open row per Device (partial unique
  index). Fields: `os_name`, `os_family`, `os_group`, `os_version`,
  `install_identifier`, `patch_state`, `config_state`.
- `operations.agent_instances` — one open row per (Device, Agent
  product). Fields: `install_token`, `agent_version`, `coverage_state`.
- Per-layer significant-field audit tables:
  `operations.asset_field_history`,
  `operations.os_instance_field_history`,
  `operations.agent_instance_field_history`.
- `operations.findings.subject_layer` +
  `operations.findings.subject_layer_entity_id` — back-reference to the
  layer entity a finding was evaluated against.
- Migrations 0050 (schema, RLS, effective-window CHECKs) and 0051
  (idempotent backfill of open-window Asset + OSInstance rows from
  current `Device` state).

### Notes
- Additive-only slice. No consumers switch to layer entities in this
  release; `v_device` and existing matviews unchanged.
- `AgentInstance` is intentionally not backfilled — the ingest resolver
  rewrite (slice 2, 0.65.0) is the authoritative writer for install
  lifetimes.
- Flat `Device` attribute columns (`device_type`, `os_name`, `os_family`,
  `os_group`, `canonical_serial`, `canonical_vm_uuid`) remain as
  denormalized cache in v1. Retirement is deferred.

## [0.63.0] — 2026-07-17 — device_offline evidence enrichment

### Why
The `stale_required_platform` gate on fully-offline devices already
landed in 0.50.7. It correctly suppressed the N-noise-per-offline-
device problem, but it also dropped the underlying evidence — an
operator triaging an offline device had to click through to the
device detail Sources tab to reconstruct "when did each source
go dark".

### Changed
- `ingest/evaluator.py::_evaluate_device_offline` now aggregates
  per-platform last-seen timestamps into the `device_offline`
  finding's `finding_details`:
  - `source_last_seen` — `{platform: iso_timestamp}` per source
  - `fully_offline_since` — the timestamp of the last source that
    held on (== `MAX(source_last_seen)`)
  - `last_seen_source` — which platform that was
- Query rewritten as a two-stage CTE (per-platform aggregation then
  per-device grouping) so `jsonb_object_agg` produces one entry per
  platform even when there are multiple `agent.*` entity types per
  platform.
- Findings queue detail column renders
  `fully offline since YYYY-MM-DD (last: <source>)` for
  `device_offline` rows.

### Docs
- BLUEPRINT §1.8 updated to document the evidence shape and the
  suppression relationship with `stale_required_platform`.

### Not changed
- Auto-resolve of `stale_required_platform` on now-fully-offline
  devices was already correct — untouched.
- No severity change on either finding type.
- No new UI beyond the queue detail-string update — the device
  detail Sources tab already shows the same per-source data as its
  primary drill-in.

## [0.62.1] — 2026-07-17 — Fix 0.62.0 crash-loop (missing resolved_at column)

### Fixed
- Migration 0048 assumed `Finding.resolved_at` existed for the
  `UPDATE ... SET closed_at = resolved_at` backfill. That column
  belongs to `AdminFinding`, not `Finding`. The wrong assumption
  raised `psycopg.errors.UndefinedColumn` during the redeploy,
  crash-looping ninja-operations after 0.62.0 pushed.
  - Dropped the backfill RunSQL. `closed_at` starts NULL for
    every pre-existing row; new transitions populate it going
    forward.
  - Dropped `resolved_at=` from `finding_resolve` and
    `findings_bulk_action` (also referenced the phantom column).
- Migration 0049 (matview) was blocked behind 0048 and lands with
  this fix in the same redeploy.

Careless mistake — top rule failure. Grep for the exact column
on the exact model before writing UPDATE/SELECT SQL against a
Django ORM model, not a same-named field on a different model.

## [0.62.0] — 2026-07-17 — Finding timestamps + Dashboard trend arrows

Wave G2 landed in a single push — three tightly-coupled slices
(model additions, matview, UI arrows). Closes real observability
gaps beyond just enabling trends.

### Added — schema
- Migration 0048: `Finding.acknowledged_at` + `Finding.closed_at`
  DateTimeField (null=True). Backfills `closed_at = resolved_at`
  where the latter was set; pre-existing acks are unrecoverable
  (rows keep NULL `acknowledged_at`). Adds
  `idx_findings_closed_at`.
- Migration 0049: `client_health_trend_current` matview — 4th
  member of the `<subject>_<layer>_current` family. Columns:
  severe_open_now / open_now / severe_open_7d_ago / open_7d_ago
  / severe_open_30d_ago. Reads from `findings.first_seen_at` +
  `closed_at` for accurate as-of counts. Refresh function
  `refresh_client_health_trend_current` registered in the
  `refresh_derived()` coordinator (now 4 steps).

### Changed — evaluator hooks
- `finding_acknowledge` sets `acknowledged_at = now()` on first
  ack (re-ack after resolve/reopen preserves the original stamp
  so MTTA stays honest).
- `finding_resolve` sets both `resolved_at` and `closed_at`.
- `finding_suppress` sets `closed_at`.
- `findings_bulk_action` respects the same rules across ack /
  resolve.

### Changed — UI
- Dashboard portfolio grid shows a trend arrow next to each
  client's severity row:
  - **▲ red** — more severe issues than 7 days ago (tooltip
    shows delta)
  - **▼ green** — fewer severe issues than 7 days ago
  - **◆ grey** — no change (only shown when 7d history exists)
- Arrow reads from the matview; if the matview is empty (fresh
  deploy pre-refresh) the row falls through to no-arrow rather
  than 500.

### Why this is a data-model win, not just a trend-arrow win
- `acknowledged_at` unlocks MTTA and ack-rate reporting on
  everything downstream — the Dashboard trend arrow is only one
  consumer.
- `closed_at` makes "was this active on date D" unambiguous for
  ALL closed statuses (resolved, suppressed, wontfix), not just
  resolved. Any future as-of query benefits.

### Known caveat
- Severity historical drift: the matview counts a finding's
  CURRENT severity for all as-of dates. In practice the
  evaluator sets severity once at emission via
  upsert-on-condition_key and rarely revisits it, so drift is
  near-zero. Documented in DESIGN §11.

## [0.61.1] — 2026-07-17 — Fix /software 500

### Fixed
- `software_page` correlated subquery referenced `sic.tenant_id`
  from the outer query while the outer `GROUP BY` only listed
  `sic.canonical_name`. Postgres raised
  `subquery uses ungrouped column`. Added `sic.tenant_id` to the
  GROUP BY (no cardinality change — the outer WHERE already
  restricts to a single tenant).

## [0.61.0] — 2026-07-17 — Standardize derived matview naming

### Why
The three derived matviews were `agent_presence_current`,
`device_session_current`, and `device_patching_scope_current`. The
two newer ones follow the `device_<layer>_current` pattern; the
oldest predates it. Rename brings all three onto one shape so
future matviews follow the pattern by copy-paste and grep sweeps
work uniformly.

### Changed — schema
- Migration 0047: `ALTER MATERIALIZED VIEW` renames on the
  matview + its two indexes (dependents keep working via OID
  references, so `device_session_current` and `v_device` do not
  need to be rebuilt).
- Refresh function rebuilt under the new name
  (`refresh_device_agent_presence_current`) — plpgsql bodies are
  literal SQL text; the old body would break at the first call
  after rename.
- Refresh coordinator (`refresh_derived`) swapped to call the
  new function.

### Changed — code
- All in-repo callers swept to the new name across
  `operations/apps/core/{views,models}.py`, `ingest/evaluator.py`,
  `ingest/identity/resolver.py`, `ingest/main.py`,
  `ingest/core/devices.py`, `ingest/agent_compliance/ingest.py`.
- BLUEPRINT, DESIGN, TODO, SESSIONS updated to reflect the new
  name.

### Not touched
- Historical migrations 0016–0044 continue to reference the old
  name — they represent the DB state at those points in time.
- CHANGELOG entries stay historical.

### Follow-up
- Metabase saved questions that reference `agent_presence_current`
  will need updating. No compatibility alias was created — the
  old name is fully gone from the DB after this migration.

## [0.60.0] — 2026-07-17 — rare_recent reframe + Classifier config UI

### Approach
`rare_recent` used to fire on every install younger than 30 days
that lived on ≤2 devices. That produced a flood on any
freshly-imaged endpoint. Reframed to answer the actual operator
question: *"did someone install something we don't recognize on
one endpoint, that we haven't already decided about?"*

### Changed — evaluator
- `ingest/software_findings.py` reads a per-tenant config row
  from `operations.evaluator_config` and merges over code defaults.
- New skip conditions:
  - Skip if any prior decision exists (approve /
    approve_publisher already skipped at loop head; reject /
    investigate now also skip).
  - Skip if the title is categorized (the classifier already
    knows what class it is — `unauthorized_*`, `eol_runtime`,
    or known-safe).
- Tightened default `rare_recent_max_age_days` 30 → 7.

### Added — schema
- Migration 0046: `EvaluatorConfig` model with unique
  (tenant, evaluator_name) and JSONB config.

### Added — admin UI
- New page **Config → Classifier** (`/admin/classifier/`).
- Every rare_recent knob exposed with human hints and defaults:
  - Enabled toggle
  - Max age (1–90 days)
  - Max devices across fleet (1–100)
  - Severity (info / low / medium / high / critical)
  - Skip if categorized toggle
  - Skip if already decided toggle
- POST validates + clamps and saves. Shows last-saved timestamp +
  user.
- Config tab strip gains a **Classifier** entry.

## [0.59.0] — 2026-07-17 — Coverage exemption UI (Wave UI-2.F slice 3)

### Added
- Endpoints `device_exemption_add` and `device_exemption_clear`
  that merge / prune keys on the device's `exemptions` JSONB dict
  (stored in `device_operator_decisions` under
  dimension='exemptions' — the existing Track O2 layer).
- Device detail Overview tab gains a **Coverage exemptions**
  card: chips per active exemption (with × to remove, confirms
  first) + collapsible **Add exemption** form (entity-type
  dropdown sourced from active coverage requirements, reason
  required).
- Wave UI-2.F complete: Issues actions + bulk toolbar (slice 1),
  patch scope override (slice 2), coverage exemptions (slice 3).

## [0.58.0] — 2026-07-17 — Patch scope override UI (Wave UI-2.F slice 2)

### Added
- Endpoints `device_patch_scope_set` and `device_patch_scope_clear`
  that write / delete rows in the existing `DevicePatchingOverride`
  table (Track O2 layer).
- Overview tab of device detail: **Patch scope** card gains a
  collapsible **Override** form with scope select (Included /
  Excluded), reason input, Save + Clear. Clearing prompts for
  confirmation and reverts the device to derived scope.
- Global flash-message strip in `base.html` — any view that calls
  `messages.info(...)` etc. now shows a bar at the top of the
  page. Removes the duplicate messages block from Issues.

## [0.57.0] — 2026-07-17 — Issue actions + bulk toolbar (Wave UI-2.F slice 1)

### Added
- Migration 0045: `Finding.snoozed_until` DateTimeField (null=True)
  + partial index. Snoozed issues hide from the queue until the
  timestamp passes.
- Endpoints on individual issues: `finding_resolve`,
  `finding_snooze` (default 7d, clamped 1–90), `finding_suppress`
  (creates a `SuppressionRule` matching the issue's subject and
  moves the issue to Suppressed).
- Bulk endpoint `findings_bulk_action` — POST ids[] + action in
  {ack, resolve, snooze}. Toolbar reports "N selected" and posts
  through a single form.

### Changed
- Issues page: table wrapped in one form; per-row Ack / Resolve /
  Snooze / Suppress buttons (Suppress prompts for confirmation).
  Bulk toolbar at top of table. Snoozed rows shown faded when
  toggled visible via the new "Snoozed" filter (default: Hide).
- `finding_acknowledge` now honours `next=` redirect so device
  detail and client detail Ack buttons return the operator to
  their calling page.

## [0.56.0] — 2026-07-17 — Admin consolidations (Wave UI-2.E)

### Changed
- Shared admin sub-nav strip (`_admin_tabs.html`) added at the
  top of every admin page. Each admin page now advertises its
  siblings so the operator never has to guess where a queue lives.
- Groups + tabs (one-word labels throughout):
  - **Review** — Clients · Devices · Merges · Software (per-tab
    live counts of items awaiting decision).
  - **Config** — Alerts · Suppressions · Requirements.
  - **Integrations** (renamed from **System** — MSP-standard
    word for "external systems we plug into") — Sources ·
    Coverage · Ingest.
- Software decisions moved into the Review group. It stays
  reachable from the Software page.
- Coverage matrix moved into the Integrations group as
  "does reality match what we require" diagnostics.
- Review total badge on the primary nav now includes pending
  software decisions.

### Added
- `nav_pending_software_decisions` count in the context
  processor (distinct installed titles with no decision at any
  scope) — feeds both the primary Review badge and the Software
  tab badge inside the strip.

## [0.55.0] — 2026-07-16 — Device detail 5-tab (Wave UI-2.D)

### Changed
- `/orgs/<slug>/devices/<uuid>/` rebuilt as a 5-tab layout with a
  persistent header and `?tab=…` navigation.
  - **Header**: breadcrumb · hostname · health dot · type badge ·
    role · online/offline state (with source list) · last contact
    · open-issue count (with severe count).
  - **Overview tab**: snapshot cards (Health · Online now · Open
    issues + severity mini-bar · Patch scope · Needs reboot ·
    Software titles) + top issues table with per-row Ack.
  - **Sources tab**: agent presence table + source-identity table.
    No source given preferential styling — Ninja is a row like
    any other.
  - **Activity tab**: unified reverse-chronological timeline of
    issue opens/reviews + last boot + last patch install (best
    effort; no historical session-transition stream yet).
  - **Software tab**: installed titles + per-title decision status
    (approve / reject / investigate / pending), with client-scope
    override marker; filter box preserved.
  - **Identity & raw tab**: canonical fields · per-source
    identifiers · placeholder for raw payloads (deferred).
- All "findings" copy → "issues"; all techspeak run through
  `humanize_label`.

## [0.54.0] — 2026-07-16 — Client detail scoreboard (Wave UI-2.D)

### Changed
- `/orgs/<slug>/` per-client page rebuilt as a client scoreboard
  matching the operator model already in Dashboard + Devices:
  - **Header**: client name · traffic-light health dot · bucket
    badge (Critical / Degrading / Healthy / No data) · sub-nav to
    Devices / Software / Policies.
  - **Overview cards**: Devices (online/offline split) · Open
    issues (with severity mini-bar) · Servers · Workstations ·
    Software titles (pending count) · In patch scope.
  - **Needs attention here**: top 15 severe/high open issues,
    scrollable, each with device clickthrough + Ack link.
  - **Offline devices to check**: top 10 offline devices ordered
    by severe-issue count then longest-offline.
  - **Coverage detail**: collapsed by default; existing agent
    coverage matrix moved under a fold rather than dominating
    the page.
  - **Sidebar**: Profile (with change form) · Known in (sources)
    · Policies summary.
  - Health rule: red = any critical, amber = any high, green =
    clean, grey = no devices.
- Fleet-mode view (`/orgs/all/`) simplified to a 4-card overview
  + client table using the shared card style.

## [0.53.0] — 2026-07-16 — Devices fleet page (Wave UI-2.D)

### Added
- New `/devices/` fleet page — entity-first browse across every
  client:
  - **Overview cards**: Total · Online · Offline · Servers ·
    Workstations · In patch scope. Each clickthrough pre-applies
    the relevant filter.
  - **OS chip strip**: All / Windows / macOS / Linux / Other,
    counts sourced from `v_device.os_group`.
  - **Filter bar**: hostname/serial search · client dropdown ·
    role · online/offline.
  - **Table**: 500-row cap, sortable columns, per-row Health
    traffic light (red = severe issues, amber = offline, green =
    healthy), hostname clickthrough to device detail, severe-issue
    count with clickthrough to filtered Issues.
  - Reads `v_device` for combined canonical + session +
    patching-scope in one query.
- Primary nav gains **Devices** link (between Clients and
  Patching), giving 6 workflow domains total.

## [0.52.1] — 2026-07-16 — Docs: Track UI-2 formalized

Backfills a proper track entry for the UI redesign work that was
accumulating ad-hoc in the git log. No code changes.

### Added
- `operations/DESIGN.md` §11.1 — updated Information Architecture
  reflecting the current nav (5 primary + search + 3 admin
  grouped).
- `operations/DESIGN.md` §11.5 — Standing UI principles (entity-
  first, human labels, admin separate, table sortable+filterable,
  Missing≠Stale, signal over noise, action-per-pixel, native
  components only).
- `operations/BLUEPRINT.md` Track UI-2 — full user-set principles,
  waves A–H with landed / in-progress / pending status, non-goals,
  and deployment batch table entry (PU2).

### Rationale
Every other track (E, C, O, 1–5) has a proper blueprint entry.
UI work didn't — commits told the story but the design context
was scattered. Anchored now so future me / other agents pick up
the plan not just the diffs.

## [0.52.0] — 2026-07-16 — Software fleet page (entity-first)

### Added
- New `/software/` page — Software is an entity ecosystem, not an
  issue category. The whole software domain gets its own page:
  - **Overview cards**: Titles · Installations · Categorized ·
    Uncategorized · Decisions · Open items
  - **Category chip strip**: All · AV · EDR · RMM · Remote access ·
    Browser · Runtime · EOL · … · Uncategorized. Sourced from
    `software_catalog.categories` JSONB arrays.
  - **Titles table**: one row per canonical product with device
    count, client count, category, decision status, latest install.
    Filter by name, category, decision status. Cap 500 rows.
  - **Sidebar**: Recent installs (last 24h) + Decisions summary
    with link to the decisions queue.
- Software nav link now points to `/software/` (was
  `/findings/?category=software`). The Issues-filtered view still
  works — the "Open items" card on the Software page clicks
  through to it.

### humanize_label additions
- Software categories (av / edr / rmm / remote_access / browser /
  runtime / eol / etc.) get proper labels.
- Decision values (approve / reject / investigate) get labels
  too.

## [0.51.1] — 2026-07-16 — Drop redundant "Matching" tile

### Fixed
- Issues page had a "Matching (N)" tile that duplicated the count
  already shown in the header ("Issues (N)"). Dropped the tile;
  the header carries the total, the severity tiles carry the
  breakdown.

## [0.51.0] — 2026-07-16 — Issues page: severity tiles + dynamic title

### Added
- Severity tile row on the Issues page (`findings_queue`):
  - Total matching + one tile per severity (critical / high /
    medium / low / info)
  - Counts respect the ACTIVE filter set — narrowing filters
    narrows tiles
  - Click a tile to toggle that severity filter on/off (adds if
    off, clears if on)
  - Color-coded left border matches severity badge color
- Dynamic page title: `/findings/?category=software` now shows
  "Software issues (N)" instead of just "Issues"; same pattern
  for any category filter.

## [0.50.7] — 2026-07-16 — Evaluator: stop stale on offline devices

### Fixed
- `ingest/evaluator.py` `_evaluate_coverage` now suppresses
  `stale_required_platform` on devices that are entirely offline
  (last contact across ALL agents older than `_LONG_OFFLINE_DAYS`
  = 7 days). The device-level `device_offline` finding already
  covers those; per-agent stale is redundant noise when the
  whole device is silent.
  - Aligns implementation with BLUEPRINT §1.8, which already
    described this behavior — code just wasn't enforcing it.
- `_auto_resolve` gained a new pass that closes existing
  `stale_required_platform` findings whose devices have since
  become fully offline. Prevents the current ~1,100 open stale
  rows from lingering after the new suppression takes effect.

### Kept firing on offline devices
- `missing_required_platform` — agent was never installed. Real
  gap regardless of current online state.
- `device_offline` — that's the whole point of it.

### Expected impact
- The Dashboard "Not reporting" card should drop substantially
  on the next evaluator cycle (many currently-open stale rows
  are on devices that have been offline > 7 days).
- Number won't go to zero — devices with SOME agents online +
  ONE agent silent will still legitimately fire stale on that
  specific agent (the real actionable case).

## [0.50.6] — 2026-07-16 — Split Missing vs Not reporting

### Fixed
- Old "Coverage" overview card conflated two different problems:
  - **Missing** (agent never installed — actionable gap, needs
    install)
  - **Stale** (agent installed but not reporting — mixed bag,
    includes offline devices where nothing can be done)
- Split into two separate overview cards:
  - **Missing agents** — count of `missing_required_platform`
    (833 across fleet). Highlighted when > 0.
  - **Not reporting** — count of `stale_required_platform`
    (1,103). Not highlighted — labeled "may include offline
    devices" so operators don't chase noise.
- Client scoreboard "Coverage gaps" column renamed to
  "Missing agents" and counts only the missing type. Clickthrough
  filters to `type=missing_required_platform`.

### Filed for follow-up
- Evaluator noise reduction: don't fire
  `stale_required_platform` when the device is entirely offline
  (already covered by `device_offline`). Every agent naturally
  stales when the device is off — per-agent stale is noise. Only
  fire when at least one other agent still reports (i.e., "device
  is up but this specific agent is silent").

## [0.50.5] — 2026-07-16 — Dashboard polish

### Changed
- "Needs immediate attention" panel now scrolls (max-height 300px,
  overflow-y auto) and pulls up to 30 clients instead of 5. Row
  count shown in the header.
- "Fleet" overview card renamed to "Devices" — user preference.
- Saved memory rule banning "fleet" from user-visible UI copy.

### Confirmed real
- Coverage: 1,935 open items is genuine. Breakdown:
  - missing_required_platform: 1,918 (1,498 critical + 420 high)
  - stale_required_platform: mostly resolved
  Translation: ~1,900 devices are missing a required agent per
  the coverage rules. Actionable, not a bug.

## [0.50.4] — 2026-07-16 — Restore overview cards

### Changed
- Replaced the muted single-line fleet strip with 6 compact
  overview cards: Fleet · Patching · Software · Coverage · Review
  · Ingest. Each is clickthrough to its dedicated page.
- Cards are visually restrained (0.75rem padding, 1.6rem value)
  so they don't dominate over the client portfolio grid below.
- Cards highlight amber when they have open items (`has-open`
  class) or red when a source is stale (`alert` class) — quick
  scan tells you where to look.

## [0.50.3] — 2026-07-16 — "Needs immediate attention" panel — tighten signal

### Fixed
- Old "Clients on fire" panel flagged 10 rows all saying "3 domains"
  because low-severity software noise (~11k `rare_recent`) hits
  every client across patching + software + coverage trivially.
  Result: no signal, dominated the page visually.
- Retightened:
  - Restrict to `severity IN (critical, high)` — drops medium
    software noise entirely, so "on fire" means real severe issues.
  - Cap to top 5 rows (was 10).
  - Renamed "Clients on fire" → "Needs immediate attention" — the
    fire metaphor was a monitoring cliché; this is what the panel
    actually IS.
  - Compact styling: smaller heading, tighter row padding, no more
    domain badge (which was meaningless when everyone was 3),
    single-line row per client.
  - Panel hidden entirely if zero clients qualify.

## [0.50.2] — 2026-07-16 — Kill "Findings" from UI copy

### Changed
- Every user-visible "Findings" / "findings" / "Finding" replaced
  with "Issues" / "issues" / "Issue" (or "Items" in low-key
  contexts). Applies to home, findings_queue, findings_admin_health,
  device_detail, coverage, patching_queue, notification_rules,
  notification_suppressions.
- Backend model + variable names untouched (Finding, findings_queue
  URL). Change is display-layer only.
- Saved permanent memory rule: "Ban the word 'findings' from UI
  copy — compliance jargon, not operator language."

## [0.50.1] — 2026-07-16 — Dashboard: fleet-operator research pass

### Changed
Applied MSP / fleet-operator research (industry lit + tooling
patterns from ConnectWise, NinjaOne, Datto, Autotask, Kaseya).
Replaced monitoring-tool language (Critical/Degrading/Healthy/
No-data as hero tiles) with what fleet operators actually scan:

- **Removed** the 4 bucket hero tiles. Their content moved into
  filter chips above the portfolio grid.
- **Added** a "Clients on fire" exception panel — clients with
  active findings in ≥2 domains (patching + software +
  coverage). Research consensus: "concurrent-domain issues"
  is a stronger signal than "highest alert count."
- **Added** a Health traffic-light column on the client
  portfolio grid (🔴 critical open · 🟠 high open · 🟢 clean ·
  ⚫ no devices). One-per-row instead of dedicated hero cards.
- **Added** filter chips above the portfolio grid: All / Needs
  attention (red+amber) / Healthy / No data. Same segmentation
  the old buckets provided, but as compact filters rather than
  dominant cards.
- **Added** Coverage-gaps column on the grid, clickthrough to
  filtered findings queue.

### Rationale from research
- Raw alert counts are considered anti-KPIs by industry sources
  (alert fatigue over action).
- Clients on fire in multiple domains is the "morning triage
  first look" question across ConnectWise, NinjaOne, Datto.
- Portfolio grid as the primary object, aggregate KPIs as a
  reference strip — matches every incumbent tool's layout.

### Deferred (need data we don't have yet)
- Trending worse (needs snapshot history)
- Renewals / QBRs due (needs contract dates)
- MRR / tier / assignment columns (needs those fields on Client)
- SLA / MTTR (needs ticket data)

## [0.50.0] — 2026-07-16 — Dashboard: client-portfolio framing

### Changed
- **Dashboard reframed as a client-portfolio scoreboard**, not a
  findings dashboard. Aligns with the reality that an MSP operator
  manages clients — findings, patching, software are facets of a
  client's state, not standalone domains that dominate the view.
  - Domain-specific hero tiles (Patching / Software / Issues /
    Awaiting Review / Ingest / Fleet) dropped. Those pages remain
    reachable via the nav.
  - New top-of-page layout:
    1. **Alerts banner** (critical findings + stale ingest) —
       only when actionable.
    2. **Fleet reference strip** — muted single line: total
       clients / devices / in-scope / sources fresh / open
       findings. Non-actionable context.
    3. **Portfolio buckets** — 4 tiles classifying clients into
       Critical / Degrading / Healthy / No data. Click to filter
       the scoreboard below.
    4. **Client scoreboard** — the primary content. Every client
       with State pill (matches bucket colors), device count,
       finding breakdown (critical/high/medium dots). Filter by
       name + bucket + paginate 25/page.
    5. **Sidebar** — two columns: "Awaiting review" (per-queue
       counts with clickthrough) and "New in last 24 hours".

### Added
- Per-client state bucket classification: `critical` (has
  critical), `degrading` (high or 5+ open), `healthy` (only low
  or none), `no_data` (0 devices reporting).
- Bucket-filter on the scoreboard (`?bucket=<name>`).
- Medium-finding count column (was hidden before) — visible in
  the scoreboard finding dots.
- Bucket labels added to `humanize_label` map so the State pill
  renders human names.

### Removed
- The "Total findings 13,557" tile — double-counted with domain
  cards and made the Dashboard feel like a bug tracker. Reference
  count still available in the fleet strip.
- The "Fleet: 5150 devices" hero tile — reference-only, demoted
  to the fleet strip.

## [0.49.0] — 2026-07-16 — Wave C: nav restructure

### Changed
- **Primary nav collapsed to 5 workflow domains:**
  Dashboard · Clients · Patching · Software · Issues
  - "Inventory" → "Clients" (rename — the page IS the client list)
  - "Security" → "Issues" (rename — clearer for MSP operators)
  - "Software" → new primary link, filters Issues to
    `?category=software` (fleet-wide software page is a follow-up)
  - "Compliance" — retired from primary nav. Coverage findings are
    still in Issues (category filter); the fleet_coverage matrix
    is retired in favor of Dashboard cards.
- **Admin cluster collapsed from 9 items to 3 grouped pages:**
  - **Review** [total badge] — merges client candidates, identity
    candidates, merge candidates under one label. Badge = sum
    across all three queues. Today links to
    `client_candidates_queue`; Wave D turns it into a tabbed page.
  - **Config** — merges notification rules, requirement profiles,
    software decisions. Links to `notification_rules_list` today;
    tabbed in Wave D.
  - **System** — merges sources, admin findings health. Links to
    `sources_status` today; tabbed in Wave D.
  - `⚙` Django admin escape hatch retained.
- Active-page detection expanded so the group highlights when
  visiting any member page.
- New context vars: `nav_pending_identity_candidates`,
  `nav_pending_review_total` (sum for the Review badge).

### Not changed (yet)
- The 9 individual admin pages still exist and are still
  reachable via their old URLs; only the nav labels have
  collapsed. Wave D creates the tabbed consolidation pages.

## [0.48.3] — 2026-07-16

### Fixed
- Dashboard "stale ingest" banner was reading from
  `source_run_queue.completed_at`, which is the retired legacy
  per-org queue mechanism — its timestamps are frozen at
  retirement time (3+ days ago). Even though ingest is running
  fine (fresh observations landing every few minutes), the banner
  screamed "all 4 sources stale." Switched to
  `MAX(entity_observations.observed_at) per platform` which is
  the actual live-data pipeline. Both the top banner AND the
  new Ingest hero tile now reflect real freshness.

## [0.48.2] — 2026-07-16

### Changed
- **Dashboard hero tiles reworked around operational domains**
  instead of raw fleet numbers:
  - **Patching** — open findings + in-scope device population
    (X of Y in scope)
  - **Software** — open software finding count
  - **Issues** — total active findings + critical / high callout
  - **Awaiting Review** — sum of pending across client candidates,
    identity candidates, and merge candidates
  - **Ingest** — X/Y sources fresh (alert-styled if any stale)
  - **Fleet** — total devices + client count (reference tile)
- Client Health card:
  - Search box: filter clients by name (`icontains`)
  - Pagination: 25 clients per page
  - Row-count in the header ("Client Health (76)")
- Home view computes: category_counts, patching_pop from v_device,
  reviews_pending across the 3 queues, source_health per source.

## [0.48.1] — 2026-07-16

### Added
- **Fleet-wide search** in the header — input field replaces the
  empty spacer left after the client-picker removal. Searches
  device hostname + serial + client name + slug (icontains). A
  unique device match redirects to device_detail; a unique client
  match redirects to that client's page; otherwise the results
  render on a `/search/` page grouped by Devices / Clients.
- `search` view + `/search/` URL + `search_results.html` template.
- Dark header input styling to match the primary-nav palette.

## [0.48.0] — 2026-07-16

### Removed
- **Tom Select ripped out entirely.** Added Wave A complexity for
  marginal gain; kept breaking (CDN load, multi-line comment
  breaking the head parse, dark/light theme fights). Native
  `<select>` works fine.
  - Removed vendored assets under `operations/apps/core/static/`.
  - Removed Tom Select `<link>`, `<script>`, CSS overrides, and
    init script from `base.html`.
  - `{% load static %}` removed (no `{% static %}` tags left).
- **Header client picker removed** — vestigial. Reachable via
  Dashboard's Client Health table + per-page Client filter.
  `client_switch` view + `/switch/` URL kept for now, unreachable
  from UI (cleanup follow-up).

### Changed
- Patching page filters — `class="ts" multiple` removed. Type,
  Client, Status, Role are all native single-select dropdowns
  with an "Any" option. Backend view still parses multi-value URL
  params (bookmarks preserved), but the UI is one-value-at-a-time.
- Header layout: brand · spacer · user-info. Wave B (fleet-wide
  search) will drop a search input into the spacer.

### Fixed (in the churn)
- Multi-line `{# ... #}` Django comment in `base.html` was
  rendering as raw text (Django `{# #}` is single-line only). The
  stray `<select>` in the comment body was breaking `<head>` and
  the page came up empty. Fixed and rule saved to memory.

## [0.46.6] — 2026-07-16

### Changed
- Header client picker becomes a properly-styled searchable
  Tom Select — with 74+ clients, native `<select>` is bad UX even
  when it renders correctly. Type-to-search dropdown replaces
  scroll-through-74-options.
- New `.ts-header` CSS variant scoped to the header only:
  dark background (`#16213e`) matching the primary-nav palette,
  light text, focused active-option `#2a2a4e`. Content-area
  Tom Select (Patching filters) keeps the default light styling
  unchanged.

## [0.46.5] — 2026-07-16

### Fixed
- Header client selector — reverted `class="ts"`. Native `<select>`
  was already styled dark to match the primary-nav header
  background; Tom Select's light theme fought that and looked
  wrong. Native dropdown is fine for a single-value picker even
  with 76 options (browsers give type-to-jump).
- Tom Select remains active for content-area filters on the
  Patching page (light backgrounds where the default light theme
  fits).

## [0.46.4] — 2026-07-16

### Fixed
- US English throughout UI copy — dropped British spellings that
  slipped in:
  - "Unrecognized device type" → "Unrecognized device type"
  - "Active organizations" → "Active organizations"
- UI principles memory updated with a "US English only in UI copy"
  rule to prevent recurrence.

## [0.46.3] — 2026-07-16

### Changed
- humanize_label rewrites — first pass was still leaking techspeak
  (e.g. "Device missing from source" — "source" is internal
  jargon). Rewrites:
  - `device_missing_from_source` → "Device removed from inventory"
  - `duplicate_platform_record` → "Duplicate device record"
  - `source_failure` → "Data source not responding"
  - `missing_required_platform` → "Required agent not installed"
  - `stale_required_platform` → "Required agent not checking in"
  - `device_unenrolled` → "No management agent installed"
  - `device_long_offline` → "Offline for an extended period"
  - `cross_client_conflict` → "Same hostname on two clients"
  - `unmapped_node_class` → "Unrecognized device type"
  - `identity_resolution_pending` → "Awaiting device identity match"
  - `software_queue_stalled` → "Software scan queue stalled"
  - `stale_collector_binding` → "Ingest connector stopped"
  - `unlinked_external_identity` → "Unresolved device from source"
  - `client_name_conflict` → "Client renamed at source"
  - `client_link_collision` → "Multiple clients claim this name"

## [0.46.2] — 2026-07-16

### Changed
- Dashboard (home) recent-findings list now renders finding type
  names through `humanize_label` — no more raw
  `stale_required_platform` / `device_offline` /
  `device_missing_from_source` in the operator's face.
- `humanize_label` filter map: added 9 missing finding types
  (device_missing_from_source, device_role_conflict,
  device_long_offline, cross_client_conflict, unmapped_node_class,
  identity_resolution_pending, software_queue_stalled,
  stale_collector_binding, unlinked_external_identity) — all
  finding types on prod now have human labels.

## [0.46.1] — 2026-07-16

### Fixed
- **Filter dropdowns rendered as inline listboxes** when the
  jsdelivr CDN was unreachable from the operator's browser
  (corporate proxy / ad-blocker / DNS filter). Tom Select JS
  never loaded, so `<select multiple class="ts">` fell back to
  native multi-select which renders every option inline instead
  of as a dropdown. Vendored `tom-select@2.3.1` under
  `operations/apps/core/static/vendor/tom-select/` — served by
  whitenoise, no CDN dependency. Script tag gains `defer` so it
  never blocks HTML parsing.
- **Header client selector** (76 clients) is now
  `<select class="ts">` — searchable dropdown with type-ahead
  instead of a 76-row native picker.

### Changed
- Tom Select CSS overrides reworked for the light theme (the app
  is light-palette, not dark as the earlier override assumed).
  Only layout tweaks + selected-item chip color remain; Tom
  Select's own default light styling handles the rest.

## [0.46.0] — 2026-07-16

Wave A of the UI redesign: human labels + searchable/multi-select
filters, proven out on the Patching page before rolling site-wide.

### Added
- `operations.apps.core.templatetags.human_labels` — `humanize_label`
  Django template filter. Maps internal identifiers (finding type
  names, scope reasons, entity types, match methods, device roles,
  OS groups, statuses) to operator-friendly labels via a central
  dict, plus small prefix parser for values like
  `policy-allowlist:<name>` and `default:<role>`. Unknown values
  pass through unchanged — never raises. Backend DB / SQL /
  condition_key strings are untouched; display-only.
- Tom Select 2.3.1 (CDN via jsdelivr) — searchable, multi-select
  dropdowns. Any `<select class="ts">` auto-upgrades on
  `DOMContentLoaded`. Dark-palette overrides in `base.html` match
  the app theme. Degrades gracefully to native `<select multiple>`
  if the CDN is unreachable.

### Changed
- Patching page filters:
  - **Type** and **Client** are now multi-select (chip-style, type
    to search). Status and Role remain single-select for now.
  - Backend accepts both `?type=X&type=Y` (native repeated params)
    and `?type=X,Y` (comma-separated for bookmarking). Client slug
    → id via `slug__in` / `client_id = ANY(...::uuid[])` in raw
    SQL queries; unknown slug → empty result set.
  - All finding type names, scope values, scope reasons, roles, and
    OS groups render via `humanize_label`. "Ack" button → full
    "Acknowledge".

### Rollout
- Wave B (next): Dashboard rework (rich cards for compliance,
  patching, software, reviews, ingest health) + fleet-wide device
  search box in the header.
- Wave C: Nav restructure (5 primary + 3 admin), rename
  findings_queue → Issues, retire fleet_coverage page, Client
  detail rework.
- Wave D: Review + Config + System tab consolidations.
- Wave D+: Device detail rewrite (5 tabs, primary-source-in-data,
  activities surface).
- Wave E: Bulk actions on Issues + Review tabs; Resolve/Snooze on
  findings; device patching-scope override + exemption toggles;
  suppress-from-row.

## [0.45.3] — 2026-07-16

### Added
- Patching page: **Role filter** (server / workstation / unknown) in
  the filter bar. Applies to:
  - Device-subject finding queries (client-subject findings like
    `patch_approval_backlog` are hidden when role is set — they
    aggregate across the whole fleet and would mix roles).
  - Per-type tile counts (tiles reflect the role filter).
  - Population summary (Total / Included / Excluded / Unmanaged
    scoped to the chosen role).
  - Scope drilldown device table (only devices of the chosen role).

## [0.45.2] — 2026-07-16

### Changed
- Patching page reorganized (feedback):
  - Filter bar moved to the top (above tiles) so tile counts
    visibly reflect the current filter selection.
  - Per-type finding tiles now honor the status + client filters
    (were global before).
  - New "Device population" section with 4 scope tiles: Total,
    In scope (Included), Excluded, Unmanaged. In-scope % shown
    inline. Excluded / Unmanaged / Included tiles clickthrough
    to a filtered device list at the bottom of the page — this
    is where Unmanaged / Excluded devices are surfaced (they
    intentionally don't fire findings, but are now browsable).
  - New device-scope drilldown: clicking a scope tile renders
    a table of devices in that bucket with hostname
    clickthrough to device_detail, scope_reason (`no-ninja-link`,
    `os-group-not-windows`, `default:server`, `device.patchingDisabled`,
    etc.), override marker, last_contact.

## [0.45.1] — 2026-07-16

### Added
- Device detail page gains a **Patching** section (card between the
  header and Active Findings). Shows effective scope + reason,
  operator override (if any), needs_reboot + last_boot, patch signal
  (ever_installed / last install date / attempts from
  `ninja_patches.device_patch_signal`), and current-online status
  from `v_device`. Bottom link to the client's patch queue. Only
  rendered when the device row exists in `v_device` (guarded).

### Changed
- `device_detail` view reads a `patching` context dict from
  `operations.v_device` + `ninja_patches.device_patch_signal` in the
  existing atomic cursor block. Single-device query, indexed lookups
  only.

## [0.45.0] — 2026-07-16

### Added
- **Patching page** at `/patching/` — dedicated triage surface for the
  5 patching finding types (Track O batch O5 engine now has a UI).
  5 per-type tiles at top (device_never_patched, patching_stalled,
  reboot_pending, patch_failing_repeatedly, patch_approval_backlog)
  with click-to-filter. Filter bar: status / type / client.
  Table shows severity, subject (hostname clickthrough to device
  detail, client name for backlog), per-type detail line (last install,
  last boot, KB count, backlog count), last-detected, Ack action.
- Primary nav gains "Patching" link between Compliance and the
  client sub-nav; badge count = open+acknowledged patching findings
  (via new `nav_patching_open` context processor entry).

## [0.44.8] — 2026-07-15

### Fixed
- `ingest/identity/resolver.py`: two `INSERT INTO operations.devices`
  statements (promotion, individual-record fallback) now include
  `os_group='Unknown'` in the column list + VALUES. os_group is a
  NOT NULL column added in migration 0033 without a DB-side default;
  omitting it caused `NotNullViolation` on device promotion (silently
  logged as "resolver: device promotion failed — continuing"). Both
  INSERT paths were missing os_group since 0033 landed — surfaced
  while verifying O5. Sync will overwrite 'Unknown' on the next
  Ninja cycle via `_sync_operations_device_roles`.

## [0.44.7] — 2026-07-15

### Added
- Migration 0044: `reboot_pending` finding type (5th patching finding
  per BLUEPRINT §5.1, previously parked pending v_device.needs_reboot).
  Category `patching`, source_module `platform.patch_findings`,
  auto_resolvable.
- `operations.refresh_derived()` coordinator function — refreshes all
  three ops derived matviews in dependency order
  (agent_presence_current → device_session_current →
  device_patching_scope_current). Grants to operations_app + ninja_ingest.
- `ingest/patch_findings.py`: new `_emit_reboot_pending()`. Reads
  `v_device.needs_reboot` + `last_boot_at`; fires on in-scope devices
  where needs_reboot=TRUE AND last_boot_at older than 3 days
  (`_REBOOT_PENDING_DAYS`).

### Changed
- `ingest/patch_findings.py` rewritten for Track O batch O5:
  * All emitters filter subjects on
    `v_device.effective_patching_scope = 'Included'` — the per-domain
    scope layer replaces legacy `ninja_core.v_active_devices`.
  * `_emit_never_patched` + `_emit_patching_stalled` now read
    `ninja_patches.device_patch_signal` (canonical rollup that matches
    Metabase counts) via a shared per-device aggregation CTE. Multi-
    Ninja-link ops devices are collapsed with BOOL_OR/MAX before
    emission — same E.3 gotcha handled in O1/O3/O4.
  * `_emit_failing_repeatedly` gains scope filter via v_device JOIN;
    aggregates per-device failing KBs into one finding.
  * `_emit_approval_backlog` gains scope filter via v_device JOIN;
    only counts patches on IN-SCOPE devices.
  * Constants promoted: `_STALLED_DAYS=35`, `_REBOOT_PENDING_DAYS=3`,
    `_FAILING_RUN_COUNT=3`, `_APPROVAL_BACKLOG_THRESHOLD=25`.

### Deferred (documented, not blocking)
- RLS retrofit on `agent_presence_current`: Postgres does not support
  RLS on materialized views. Effective scoping already flows through
  joins to `operations.devices`; direct SELECT by trusted roles
  (metabase_ro, operations_readonly) remains an accepted risk.
  Security-barrier view wrappers filed for a future batch if the
  boundary needs tightening.
- Metabase question audit: run out-of-band against Metabase's SQLite/
  MySQL metadata to grep for `d.exemptions` / `.exemptions` — none
  expected today (exemptions only had 69 rows and no Metabase card
  surfaced it), but confirm before P7 cutover.

## [0.44.6] — 2026-07-15

### Added
- Migration 0043: patching scope layer (Track O batch O4).
  - Config: `patching_scope_signal` (10 seeded rules, documentation of
    the resolution), `patching_scope_default` (workstation→Included,
    server→Excluded, unknown→Unmanaged), `patching_scope_policy_allowlist`
    (imported from `ninja_core.patching_enabled_policies`).
  - Derived: `operations.device_patching_scope_current` matview. Per
    ops device; multi-Ninja-link collapse via `DISTINCT ON (d.id)`;
    latest custom_field values via `DISTINCT ON (entity_id,field_name)`
    with the existing (entity_type, entity_id, field_name,
    last_observed_at DESC) index. Non-Ninja-linked or non-Windows
    devices → 'Unmanaged'. Includes `scope_reason` (`device.patchingDisabled`,
    `policy-allowlist:<name>`, `default:server`, etc.) for operator
    triage.
  - Operator override: `operations.device_patching_override` typed
    table (`scope CHECK IN Included/Excluded`, one row per device,
    RLS on, grants match other tenant tables).
  - Refresh function `operations.refresh_patching_scope_current()`
    with CONCURRENTLY unique index.
  - `v_device` extended (CREATE OR REPLACE — additive columns):
    `patching_scope_derived`, `patching_scope_reason`,
    `patching_scope_computed_at`, `patching_scope_override`,
    `patching_scope_override_reason`, `effective_patching_scope`
    (COALESCE override → derived → 'Unmanaged').

### Changed
- `ingest/core/devices.py`: new `refresh_patching_scope_current()`
  wrapper calling the Postgres refresh function.
- `ingest/main.py` `run_once()`: calls `patching_scope_refresh` after
  `custom_fields` ingest — matview depends on both
  `ninja_core.custom_field_values` (from custom_fields) and
  `operations.devices.os_group`/`device_role` (already set by
  `_sync_operations_device_roles` inside `devices.run`).

### Parity target
- `ninja_core.v_active_devices`: 4,083 Windows-only devices (1,663
  Excluded / 2,420 Included).
- Ops target for `device_patching_scope_current`: same Included /
  Excluded breakdown for Ninja-linked Windows devices; all other
  devices → 'Unmanaged'. Verified post-deploy.

## [0.44.5] — 2026-07-15

### Added
- Migration 0042: `operations.v_device` effective view (Track O batch O3).
  Joins canonical `operations.devices` + `device_session_current` (O1) +
  `device_operator_decisions` pivoted for `dimension='exemptions'` (O2).
  `WITH (security_invoker = true)` so RLS on the base table applies to
  view queries. Grants match the base tables. Consumers wanting derived +
  operator + canonical in one flat read use this — never the storage.

### Changed
- `ingest/evaluator.py` `_evaluate_coverage`: reads exemptions via
  `LEFT JOIN operations.device_operator_decisions` instead of
  `d.exemptions`. Same semantics, sourced from the new storage.
- `ingest/identity/resolver.py`: two `INSERT INTO operations.devices`
  statements (promotion, individual-record fallback) drop the
  `exemptions` column from the column list (both previously inserted
  literal `'{}'::jsonb`, which is now the DB-side default absence).
- `ingest/core/devices.py`:
  - `_sync_operations_device_roles` drops the exemptions clause from
    its `UPDATE`.
  - New `_sync_operations_device_exemptions` upserts to
    `device_operator_decisions` from the Ninja "no av" marker with the
    same semantics as before (merge on marker present, remove
    `agent.edr` key when marker gone, preserve operator-set values).
    Called after `_sync_operations_device_roles` on each Ninja cycle.
    `ninja_state` CTE aggregates via `BOOL_OR` across multi-link ops
    devices to keep exactly one row per `(tenant, device)` before
    upsert (same E.3 gotcha that hit O1).

### Removed
- `operations.devices.exemptions` column (SeparateDatabaseAndState —
  DB `ALTER TABLE ... DROP COLUMN`, Django state `RemoveField`). Data
  already migrated to `device_operator_decisions` in 0041. Read via
  `v_device.exemptions` going forward.
- `Device.exemptions` field on the ORM model.

## [0.44.4] — 2026-07-15

### Added
- Migration 0041: operator decisions layer (Track O batch O2).
  - `operations.operator_decision_dimensions` registry (global
    reference table) — pins the set of valid dimensions for the
    polymorphic operator-decision tables, with per-dimension
    `value_type` (enum/boolean/text/json) + `allowed_values`.
  - `operations.device_operator_decisions` polymorphic table
    (per-device standalone operator decisions) with unique
    `(tenant, device, dimension)`. RLS + grants.
  - BEFORE trigger `validate_operator_decision()` — validates the
    dimension exists and is enabled, and enforces the value shape
    against the registered `value_type` + `allowed_values`.
  - Seeds `exemptions` dimension (value_type=json).
  - Migrates every non-empty `Device.exemptions` into
    `device_operator_decisions` rows under dimension='exemptions'.
    Device.exemptions column retained until O3 (v_device wire-up).

## [0.44.3] — 2026-07-15

### Fixed
- Migration 0040 `device_session_current`: unique index creation on
  `(tenant_id, device_id)` failed with a duplicate key because ops
  devices with multiple Ninja `device_links` (legal per BLUEPRINT
  E.3 — multi-link per source) produced multiple rows in the
  `device_reboot` CTE. Added `DISTINCT ON (dl.device_id) ORDER BY
  dl.device_id, lns.snapshot_at DESC` so each ops device gets one
  reboot row (freshest snapshot among linked Ninja devices).

## [0.44.2] — 2026-07-15

### Fixed
- Migration 0040 `device_session_current` matview creation hung on
  `DataFileRead` — the `DISTINCT ON (dl.device_id) ORDER BY dl.device_id,
  ns.snapshot_at DESC` couldn't use the `(device_id, snapshot_at DESC)`
  index on `ninja_core.device_snapshots` because the ORDER BY was
  across the join to `device_links`. Postgres fell back to a full
  HashJoin + Sort on millions of snapshot rows. Fix: compute latest
  snapshot per Ninja device with `DISTINCT ON (ns.device_id)` in a
  standalone CTE first (uses the primary index directly, index-only
  skip scan), then join to `device_links` on the small aggregated
  result. Query drops from indefinite to milliseconds. First deploy
  of 0040 (a41fbcb) was killed via `pg_cancel_backend()` before it
  completed; the transaction rolled back so no artifacts remained.

## [0.44.1] — 2026-07-15

### Added
- Migration 0040: `operations.device_session_current` matview (Track O
  batch O1). Per-device rollup across `agent_presence_current` +
  latest Ninja `device_snapshots` — carries `last_contact_at`,
  `last_observed_at`, `is_online_any`, `online_sources[]`,
  `source_count_active`, `needs_reboot`, `last_boot_at`,
  `last_power_state`, `computed_at`. Powers the findings-queue
  online-source map today and the `reboot_pending` finding coming
  in batch O5. Concurrent-refresh unique index; refresh function
  `operations.refresh_device_session_current()`; grants match
  `agent_presence_current` (operations_app, ninja_ingest,
  operations_readonly, metabase_ro SELECT).

### Changed
- `ingest/core/devices.py` `_refresh_agent_presence_current()`: now
  refreshes both `agent_presence_current` and
  `device_session_current` in dependency order. Same in
  `ingest/identity/resolver.py`. Formalized as a refresh manifest
  in O5.
- `operations/apps/core/views.py` `findings_queue`: online-source map
  now reads pre-aggregated `online_sources[]` from
  `device_session_current` instead of computing it inline per request
  off `agent_presence_current`. Same behavior, one fewer aggregation.

### Fixed
- `operations/DESIGN.md` §3.8: corrected the tenant-scoping-on-matviews
  claim. Postgres does not support RLS on materialized views; effective
  scoping comes through joins to RLS-enabled canonical tables. Trusted-
  role direct SELECT is documented as accepted risk. Tightening via
  security-barrier view wrappers filed for O5.

## [0.44.0] — 2026-07-15

### Added
- `operations/DESIGN.md` §1 principle #7 + new §3.8: standing four-layer
  storage separation architecture — canonical, derived matview, operator
  decisions (per-domain typed OR polymorphic for simple), effective view
  (`v_<entity>`). Per-domain top-to-bottom; shared reads via effective
  views; sharing only where the output shape is genuinely uniform.
  Applies to every ops entity going forward.
- `operations/BLUEPRINT.md` Track O: five-batch storage separation pass
  (O1 session-state rollup, O2 operator-decisions layer, O3 `v_device`
  effective view, O4 patching_scope layer per-domain, O5 patch_findings
  refactor + `reboot_pending` + refresh coordination + RLS retrofit +
  Metabase audit). Deployment batch table gains `PO` between P6 and P7.
- `operations/TODO.md` Backlog: five O1–O5 tasks with acceptance gates.

### Rationale
- Columns on `operations.devices` had been mixing (1) identity, (2)
  values recomputed every ingest cycle, (3) permanent operator
  decisions, and (4) session state — no signal to a reader which was
  which. Rule changes silently invalidated stored values; sync could
  clobber operator decisions.
- The four-layer split gives every field one writer and one meaning,
  and adding a new scope domain becomes a mechanical template
  application (no schema redesign).

## [0.43.0] — 2026-07-08

### Added
- `/orgs/<slug>/software/`: per-client software inventory browse page.
  Aggregates `software_installations_current` by product (name + publisher),
  shows device count, versions, last seen. Name search + publisher filter +
  pagination (100/page). Empty-state message when queue is disabled.

## [0.42.0] — 2026-07-08

### Changed
- Renamed ingest container from `ninja-ingest` to `operations-ingest`
  (`docker-compose.yml` container_name). Updated all `docker exec` examples
  in `ingest/` module docstrings, `HANDY_COMMANDS.md`, and `TROUBLESHOOTING.md`
  to match. (Phase 12)

## [0.41.0] — 2026-07-08

### Added
- `/findings/`: enhanced entity findings review page — confidence, client,
  and type filters; paginated (50/page); hostname from finding_details;
  one-click Acknowledge action. (Phase 11)
- `/admin/findings/health/`: new admin-findings health page — platform-level
  findings (queue health, identity backlogs). Acknowledge action. (Phase 11)
- `POST /findings/<id>/ack/` and `POST /admin/findings/<id>/ack/`: acknowledge
  endpoints for entity and admin findings respectively. (Phase 11)

## [0.40.0] — 2026-07-08

### Added
- `ingest/evaluator.py`: platform evaluator — reads `coverage_requirements`
  and `entity_observations` to UPSERT entity findings; also opens
  `device_missing_from_source` and `device_long_offline` lifecycle findings;
  auto-resolves findings where condition clears. Scheduled every 4 h in
  main.py. (Phase 8)
- `ingest/agent_compliance/ingest.py`: calls `platform_evaluate(tenant_id=1)`
  after each full AC run and refreshes `agent_presence_current`. (Phase 9)
- `operations/apps/core/migrations/0016`: creates
  `operations.agent_presence_current` materialized view (agent.* entity
  observations aggregated per device/platform) with CONCURRENT refresh
  function. Grants SELECT to all reader roles. (Phase 10)

## [0.39.0] — 2026-07-08

### Added
- `ingest/core/devices.py`: syncs `operations.device_links.last_seen_at` and
  `missing_since` on every Ninja full-pull (Phase 5). Runs inside the same
  transaction as the ninja_core upserts.
- `ingest/identity/fast_path.py`: inline device identity resolver — exact
  source link → unique serial → unique hostname (Phase 6).
- `ingest/identity/resolver.py`: polling v1 resolver for `entity_observations`
  with NULL device_id — scans, resolves by hostname, logs multi-match misses
  (Phase 6).
- `operations/apps/core/migrations/0015`: seeds SentinelOne, ScreenConnect,
  LogMeIn as Sources + SourceInstances + SourceBindings with fixed UUIDs
  (Phase 7).
- `ingest/agent_compliance/ingest.py`: dual-writes S1/SC/LMI observations into
  `operations.entity_observations` after the existing platform_observations
  write. Uses `fast_path.resolve_device_fast` for inline device resolution
  (Phase 7).

## [0.38.0] — 2026-07-08

### Added
- `operations.coverage_requirements`: per-tenant/client gap thresholds
  (entity_type, platform, device_scope, severity, gap/confidence windows).
  RLS enabled. (migration 0014)
- `operations.admin_findings`: platform-health findings (condition_key unique
  partial constraint on active). RLS enabled. (migration 0014)
- `operations.queue_registry`: queue governance catalog (no tenant scope,
  no RLS). Seeded with 4 queues: software.scheduled, software.demand,
  software.activity, identity.resolution. (migration 0014)
- `operations.identity_candidates`: pending device-pair merge suggestions
  (unique partial constraint on pending pairs). RLS enabled. (migration 0014)
- `operations.notification_rules`: rule engine layer over NotificationRoute
  (finding_class, min_severity, match_criteria, cooldown_hours). RLS enabled.
  (migration 0014)
- `operations.notification_state`: cooldown tracking per rule+fingerprint.
  RLS enabled. (migration 0014)
- `operations.notification_events`: delivery audit log. RLS enabled.
  (migration 0014)

## [0.37.0] — 2026-07-08

### Added
- `operations.finding_types`: `finding_class` (entity/admin), `source_module`,
  `auto_resolvable` fields. All 10 existing types back-filled with entity class.
  6 new finding types seeded: `device_missing_from_source`, `device_long_offline`,
  `device_stale_data`, `missing_required_platform`, `software_queue_stalled`,
  `identity_resolution_pending`. (migration 0013)
- `operations.findings`: `condition_key` (dedup hash, unique per active finding
  per tenant), `confidence` (possible/probable/confirmed), `last_detected_at`,
  `client` FK. (migration 0013)

## [0.36.0] — 2026-07-08

### Added
- `operations.software_installations_current`: three-state staleness columns
  (`stale_since`, `stale_reason`, `deleted_at`, `deleted_reason`). Rows are
  no longer hard-deleted when absent from a software pull — they are marked
  stale instead. Reappearance clears `stale_since`. (migration 0011)
- `operations.device_links`: `missing_since` column tracks when a Ninja device
  last disappeared from the full pull. (migration 0012)
- `operations.devices` / `operations.clients`: full lifecycle columns —
  `created_at`, `created_reason`, `updated_at`, `updated_reason`,
  `stale_since`, `stale_reason`, `deleted_reason`. (migration 0012)

## [0.35.5] — 2026-07-07

### Fixed
- Preserved Operations admin sessions across container redeploys by making
  the startup admin-password sync skip password re-hashing when the
  configured password already matches the stored admin password.

## [0.35.4] — 2026-07-03

### Fixed
- Increased the Postgres container shared-memory allocation to prevent
  materialized-view refreshes from failing with dynamic shared-memory
  `No space left on device` errors.

## [0.35.3] — 2026-07-03

### Changed
- Restored the Client Patch Review fully-patched breakdown cards and
  rewrote them to use a fast device-level missing-patch check instead
  of rebuilding the full installed/missing patch universe.
- Rebuilt `Patching Devices per Day` on `latest_install_outcome` instead
  of raw patch facts.
- Moved warning-category, warning trend, and reboot trend dashboard
  cards onto activity reporting materialized views.

### Added
- Added recent patch-warning and reboot activity reporting materialized
  views, refreshed with the existing activity summary refresh.

## [0.35.2] — 2026-07-03

### Changed
- Rebuilt `Patch Installs per Day` on `latest_install_outcome` instead
  of raw patch facts so the broad trend card uses the existing patch
  reporting view.
- Reworked broad reboot and warning-category cards to filter recent
  activity before joining device/client context.
- Removed the two slow Client Patch Review analytical breakdowns
  (`fully patched by device type` and `fully patched by OS`) from the
  active layout until they can be rebuilt on a dedicated reporting
  rollup.

### Added
- Added targeted indexes for recent install, patch-warning, and reboot
  dashboard activity queries.

## [0.35.1] — 2026-07-03

### Fixed
- Fixed Metabase bootstrap import failure from applying card-title
  overrides to `UTILITY_CARDS` before the utility card list was defined.

## [0.35.0] — 2026-07-03

### Changed
- Reworked the patch dashboard information architecture around the
  approved operator flow: Command Center, Client Patch Review, Device
  Work Queue, Device Detail, Patch Evidence, Patch Trends, and
  Activity Search.
- Renamed active dashboards in place using legacy dashboard names so
  existing Metabase dashboard IDs are preserved where possible.
- Removed `Overall Patching Status` and `Device Patching Status` from
  the active dashboard build/navigation; their useful concepts are
  merged into the remaining workflow pages.
- Clarified card titles for fleet devices, client status, patch
  failures, approval blockers, device work queues, and patch evidence.
- Device Detail now requires a selected device instead of running broad
  fleet detail queries on direct page open.
- Removed the two slowest Trends cards from the visible layout until
  they can be rebuilt on optimized reporting views.

### Added
- `DASHBOARD_PLACEMENT_MAP.md` records the card-by-card placement,
  timing baseline, and keep/move/drop decisions used for this redesign.
- Bootstrap cleanup archives retired duplicate dashboards after active
  dashboards are resolved.

## [0.34.7] — 2026-07-02

### Changed
- Client Patch Status now requires one selected client for the top KPI
  band: the status card shows `Choose one client` when the page is
  unfiltered or multi-client, and the top numeric cards stay blank
  instead of showing misleading all-client totals.
- Clarified Client Patch Status top-card titles so operators can tell
  whether a card counts devices, patches, or client status.

## [0.34.6] — 2026-07-02

### Fixed
- Triage warning/error category activity cards now honor the
  `Message Contains` filter so operators can find devices with similar
  patch messages across the fleet.
- Added trigram and activity type/time indexes for faster patch activity
  message searches.

## [0.34.5] — 2026-07-02

### Fixed
- Reworked Client Patch Status device-type and OS fully-patched
  breakdowns to use the device-level patching-device formula instead
  of grouping the full patch universe directly in each chart.
- Reworked the Client Patch Status warnings scalar to use
  `ninja_activities.device_activity_signal.warning_events_30d` instead
  of scanning raw activity rows on page load.

## [0.34.4] — 2026-07-02

### Fixed
- Rewrote Command Center's `Patches Installed Awaiting Reboot` card to
  start from reboot-needed devices and use existing patch/activity
  rollups instead of aggregating raw patch and activity tables on every
  load.
- Added an index for installed patch lookups by device on
  `ninja_patches.latest_install_outcome`.

## [0.34.3] — 2026-07-02

### Fixed
- Patching/Stalled/Never-Patched scalar click-throughs now use dashboard
  parameter mappings instead of URL-only presets, so current Client,
  Device Type, and Patching Scope filters carry into Device Status.

## [0.34.2] — 2026-07-02

### Changed
- Renamed the patch dashboard model from role/health language to
  functional client/status language: Client Patch Status, Triage, Patch
  Trends, status, Needs Action, Watch, and Good.
- Metabase bootstrap now renames legacy dashboard identities in place
  while matching legacy card UIDs, avoiding duplicate cards when
  `Org Overview`, `Issues`, or `Trends` already exist.
- Command Center now orders clients by explicit patch status rules and
  shows the reason behind the status.
- Client Patch Status keeps the quick questions up front: patching
  enabled, successful scans, recent installs, and devices needing action.

### Added
- Triage subqueues for scan gaps, reboot blockers, approval backlog, and
  stalled or never-patched devices.
- Device Drilldown summary fields for current problem, suggested action,
  last install attempt, last failure, and full failure/warning messages.

### Fixed
- Restored/preserved Client Patch Status click-through aliases on client,
  device, patch state, KB, and device type columns, including the top
  problem-device table.

## [0.34.1] — 2026-07-01

### Changed
- Reframed patch dashboard navigation labels around functional areas:
  `Org Overview` now appears as Customer Health and `Issues` appears
  as Triage while preserving the stored Metabase dashboard identities.
- Command Center's `Clients Needing Attention` table now ranks
  customers by health tier and reason using scan, install, failure,
  stalled, reboot, approval, and warning signals.
- Customer Health's top band now answers the core operational questions:
  health tier, patching-enabled devices, scanned successfully in 30d,
  installed recently in 30d, and devices needing attention.
- Triage queue now includes priority, blocker, full failure/warning
  messages, and warning-only devices; issue filters include a free-text
  `Message Contains` search for finding devices with similar errors.

## [0.34.0] — 2026-06-30

### Added
- New `Ninja — Utilities` dashboard with an Activity Search card.
  Free-text filters on `message` and `subject`, plus multi-selects for
  activity type, organization, severity, and a device dropdown.
  Results link out to the Ninja device dashboard via a per-row
  "Open in Ninja" link, and the device column drills into Device
  Drilldown.
- "Open in Ninja" link column added to the Device Drilldown's Device
  Summary card. Uses the Ninja URL
  `https://amrose.rmmservice.com/#/deviceDashboard/<id>/overview`.

### Changed
- Click-behavior pass now deep-merges `column_settings` so per-column
  display settings baked into a card spec (e.g. `view_as: "link"`)
  survive when per-column click behaviors are written for unrelated
  columns on the same card.

## [0.33.7] — 2026-06-22

### Fixed
- Refined Inventory merge candidates so a valid serial seen in multiple
  platforms is treated as normal same-device evidence unless it maps to
  more than one reconciled inventory device for the same customer.

## [0.33.6] — 2026-06-22

### Changed
- Materialized Inventory current facts so Metabase reads stored current
  relations instead of recomputing source observations, serial quality,
  identity conflicts, merge candidates, unresolved records, and summary
  metrics on every dashboard load.
- Inventory current facts now refresh after patch ingest, agent
  compliance collection, and agent compliance evaluation.

## [0.33.5] — 2026-06-21

### Changed
- Moved exact row-count denominators for capped Inventory and Patching
  detail tables into separate scalar cards. Limited tables no longer use
  `COUNT(*) OVER()`, so they can return their first 300/500 rows without
  waiting for the full matching result count.

## [0.33.4] — 2026-06-21

### Changed
- Added explicit row-cap context to capped Inventory and Patching detail
  tables. Card names now show the cap, and result rows include the total
  matching rows after filters so capped views are not mistaken for the
  complete dataset.

## [0.33.3] — 2026-06-21

### Changed
- Optimized Inventory Overview KPI cards to query their target current
  views directly instead of repeatedly filtering the aggregate inventory
  summary view.
- Reduced initial row loads on broad Inventory detail cards so dashboard
  navigation opens faster while keeping full filtering available.
- Optimized Compliance Today summary cards to read from the current
  device-state view instead of the human presentation view.
- Reduced the default row load on the broad Patching patch-detail table
  to improve initial dashboard navigation speed.

### Added
- Added dashboard performance indexes for shared platform observation
  lookups used by Inventory and Compliance source/device matching views.

## [0.33.2] — 2026-06-21

### Fixed
- Fixed the Inventory Overview "Merge candidates" KPI using the same
  internal card key as the Identity Review detail table. The top row
  now keeps a scalar KPI, while the detail table remains on the
  Identity Review dashboard.

## [0.33.1] — 2026-06-19

### Changed
- Inventory merge candidates now include hostname/Mac-safe same-device
  candidates from the existing compliance identity rules, in addition
  to serial-based candidates. Inventory Identity Review is now the
  single dashboard queue for current same-device candidate evidence.

## [0.33.0] — 2026-06-19

### Added
- Added a separate Inventory module backed by the new `ninja_inventory`
  schema. Inventory views now surface current source observations,
  resolved inventory devices, unresolved/excluded source records,
  serial quality, identity conflicts, and serial-based merge candidates
  without hiding placeholder or invalid serial values in code.
- Added a standalone Inventory Metabase collection with Overview,
  Devices, Identity Review, Serial Quality, and Source Records
  dashboards. Compliance dashboards are left in place.
- Added an inventory-domain bootstrap module so future ingest/bootstrap
  separation can proceed by domain instead of adding inventory cards to
  the compliance bootstrap.

## [0.32.9] — 2026-06-19

### Added
- Mac device reconciliation now applies a conservative separator-free
  match key when the same loose hostname is observed under multiple
  platforms for the same customer and no platform has duplicate device
  IDs under that key. This collapses pairs such as
  `GCNY-25s-iMac.local` and `GCNY-25's iMac` without changing raw
  platform observation history.
- Added operator-controlled device-name merge decisions using the
  existing `human_decisions` table (`same_device`). The Devices
  dashboard now includes suggested device name merges with a `Merge`
  action, and `/a/md` records manual merges for future evaluations.

### Changed
- Device platform drilldown now resolves raw observation evidence
  through raw, stored, Mac-safe, and manual match keys so merged device
  rows still show per-platform hostnames and IDs.

## [0.32.8] — 2026-06-18

### Changed
- `v_native_device_customer_conflicts` and
  `v_unmapped_platform_customers` now evaluate only each source's
  latest successful run. Historical pre-id-link observations remain in
  raw history, but operational guardrail counts now reflect current
  state instead of old contamination.

## [0.32.7] — 2026-06-18

### Changed
- Enforced the client-id-first matching model in both full collection
  and evaluate-only runs. Evaluate now consults
  `client_platform_links` before aliases, preventing renamed customers
  from being split by stale display names.
- Alias resolution now records source-aware methods
  (`manual_alias`, `seed_alias`, `alignment_alias`, etc.) and refuses
  ambiguous active alias keys instead of silently choosing the first
  matching customer.
- Finding signatures now use `client_id` instead of customer display
  name, so customer renames do not create new finding identities.
- Resolution confidence now reflects match strength: platform ID /
  source-bound matches score highest, followed by manual, seed, and
  generated aliases.

### Added
- Identity guardrail views for alias collisions, platform-link
  collisions, cross-customer hostnames, native platform device IDs seen
  under multiple customers, and unmapped platform customer names.

## [0.32.6] — 2026-06-18

### Changed
- Ignored customer names now show where the name was observed in the
  last 24 hours, including platform, source group IDs, observed name,
  and device count. Placeholder reasons are written in operator-facing
  language instead of internal migration wording.
- Ignored customer names now expose both `Restore` and `Promote`
  actions, including seeded placeholder rows. Restoring disables the
  exclude row but keeps audit history; promoting creates/accepts a real
  customer.
- Removed the UI-only block that prevented placeholder-looking names
  from being added as aliases. Explicit operator actions now win over
  code placeholder policy.

## [0.32.5] — 2026-06-18

### Changed
- Customer/org names are no longer dropped from discovery solely
  because code classifies them as placeholders. Names now fall into
  an explicit bucket: active client/link, candidate/review queue, or
  `org_excludes`.
- Seeded `default site`, `default`, `unknown`, and `various` into
  `org_excludes` so hardcoded placeholder names are visible in the
  ignored customer names table instead of being hidden by code.

## [0.32.4] — 2026-06-18

### Fixed
- Disabled aliases owned by demoted clients and removed stale
  `org_alignment_current` rows whose `org_name` no longer matches
  the enabled canonical client. This prevents preserved duplicate
  rows like client_id 1300 from appearing in matching/display paths.
- Alias loading now ignores aliases whose owning client is disabled
  or demoted, while leaving aliases on active clients unchanged.

## [0.32.3] — 2026-06-18

### Fixed
- Customer/platform-name dashboard tables now display current
  `client_platform_links` names before falling back to aliases, so
  stale generated aliases like Ninja `CPS` no longer appear as the
  current Ninja name for City Painting after the stable ID link has
  been repaired.
- Alignment rebuild now treats only manual aliases as explicit
  operator config. Current ID-link names outrank old seed aliases,
  preventing pre-rename seed data from overriding the current upstream
  Ninja name.

## [0.32.2] — 2026-06-18

### Fixed
- Migration 053's backfill cross-contaminated `client_platform_links`
  because it joined `platform_observations` to
  `compliance_matrix_current` on `norm_name` alone (no client_id).
  Any hostname collision between unrelated customers attributed the
  upstream `platform_group_id` to whichever client had the lowest
  `client_id` after the `ORDER BY client_id ASC` tiebreak. In
  practice, client_id 7 (City Painting) was attached to Abco - Omni
  Dental, Landau Realty, and Prompt across all three platforms.
- Migration 054 TRUNCATEs `client_platform_links` and re-backfills
  using each observation's at-ingest `resolved_client_id` from
  observations recorded BEFORE migration 053 applied (pre-053
  resolutions used name-only matching and are not contaminated).
  Tiebreak is now `COUNT(*) DESC, client_id ASC` so the majority
  owner of each `(platform, group_id)` wins. Historic resolutions
  to demoted client_ids (1299/1300/1301) are remapped to the kept
  ones (22/7/10).
- Matrix repair is automatic: `_write_matrix` deletes and
  re-inserts `compliance_matrix_current` on every run, so the
  next `/run/agent-compliance` rebuilds it correctly against the
  repaired link table. No manual matrix cleanup needed.

## [0.32.1] — 2026-06-18

### Fixed
- Migration 053 hit `UNIQUE(clients.client_name)` when renaming the
  kept client (e.g., client 22 → `PCHC - Parent Care`) because the
  duplicate (client 1299) still held that name. Reordered the
  migration: rename + demote duplicates first (suffix
  `[demoted ... dup of #N]`) to free the canonical names, then
  rename the kept clients. Behavior otherwise unchanged.

## [0.32.0] — 2026-06-18

### Added
- `ninja_agent_compliance.client_platform_links` table — stable
  mapping of `(platform, platform_group_id, source_id)` →
  `client_id`. Replaces name-matching as the primary identity
  mechanism for cross-run customer continuity. Migration 052.
- Backfill migration 053 populates link rows from the last 30 days
  of observations + matrix, then resolves the three duplicate Ninja
  client pairs that name-only discovery created during the
  2026-06-18 platform renames (PCHC, City Painting via CPS, GF
  Supplies).
- `load_id_links()` and `upsert_id_links_from_observations()` in
  `ingest/agent_compliance/config_loader.py`.

### Changed
- `resolve_client_id()` now consults `client_platform_links` before
  falling back to name/alias lookups. Existing alias data is
  unaffected.
- `sync_clients_from_observations()` will no longer mint a duplicate
  `clients` row when an upstream rename produces a new
  `platform_group_name` for an already-linked `platform_group_id`.
  The existing client_id is reused and its `client_name` is
  refreshed from the latest Ninja observation (Ninja is
  authoritative when platforms disagree).
- Every `/run/agent-compliance` now maintains the link table from
  resolved observations and refreshes `clients.client_name` from
  current Ninja names. Re-loads `clients` before matrix build so
  the rename propagates to `compliance_matrix_current.client_name`
  in the same run.

### Notes
- Aliases (`client_aliases`) retain their role for **cross-platform
  identity glue** (e.g., S1 group id ↔ Ninja org id ↔ same
  customer). They are no longer the rename-mitigation mechanism.
- Operator action after Portainer redeploy: run
  `curl -fsS -X POST http://127.0.0.1:8090/run/agent-compliance`,
  then verify with the new validation queries in
  `HANDY_COMMANDS.md`.

## [0.31.0] — 2026-06-16

### Added
- Operator form for adding a per-customer ScreenConnect source.
  - New endpoint `GET /agent-compliance/action/add-source` (alias
    `/a/as`). Without `confirm=1` it renders an HTML form: customer
    dropdown, source slug, display name, base URL. With `confirm=1`
    it inserts the `platform_sources` row (platform=`ScreenConnect`,
    `is_shared=false`, env var refs computed from the slug) and
    returns a success page with the exact env var names the operator
    must set in `/amr-ch-01_data/ninja-dashboard/.env`.
  - Setup dashboard gains a `Add a per-customer ScreenConnect source`
    card under Routes and sources; clicking it opens the form.

### Notes
- Secrets do not pass through the form. The form only records env
  var names (`SC_<SLUG>_EXT_GUID`, `SC_<SLUG>_SECRET_KEY`); the
  actual values stay on the host in `.env`.
- v1 covers ScreenConnect only since that's the per-customer
  tenant case. Other platforms (Ninja, SentinelOne, LogMeIn) are
  typically shared and rarely added.

## [0.30.0] — 2026-06-16

### Added
- Unresolved-group evidence in `v_device_state_current` (migration
  051). A new `unresolved_evidence` CTE scans recent
  `platform_observations` where `resolved_client_id IS NULL` and
  surfaces `unresolved_matches` (jsonb) and `unresolved_platforms`
  (text[]) at the end of the view. A device classified `Missing`
  that is actually checking in under, say, SentinelOne's `Default
  site` (not mapped to a customer) now reads
  `Missing X; also under unresolved (SentinelOne) — fix site/alias
  mapping` and gets `needs_review = true` with `review_reason =
  'Found under unresolved group — fix site/alias mapping'`.
- macOS family detection in `os_family`: explicit buckets for
  `macOS 10` through `macOS 15`, plus `macOS 26` and
  `macOS (other)`. macOS / OS X / Darwin variants all map cleanly.
- Linux family detection: single `Linux` bucket covering Linux /
  Ubuntu / CentOS / Debian / Red Hat strings.
- Added the new OS family values to `OS_FAMILY_VALUES` in
  `metabase_bootstrap.py` so the Devices dashboard `OS family`
  filter dropdown lists them.

### Notes
- Macs were already being ingested (no platform filter in the
  agent_compliance Ninja fetcher) — they were just bucketed as
  `Other` until this commit.
- Per-OS required_platforms is **not** changed here. Macs / Linux
  still inherit the client's required platform list, so Macs that
  shouldn't have LogMeIn (for example) will still show as Missing
  until per-OS overrides land. Tracked as a follow-up.
- New columns (`unresolved_matches`, `unresolved_platforms`) are
  appended at the end of the view, so downstream views
  (`v_device_work_queue`, `v_all_devices_human`) keep working
  without rebuild.

## [0.29.1] — 2026-06-16

### Added
- Device rename detection. At the end of each full
  `agent_compliance.run()`, the ingest compares this run's
  observations to the latest prior observation per
  `(client_id, platform, platform_device_id)`. When the `norm_name`
  differs, a row is inserted into a new `device_renames` table
  recording old/new hostnames, platform, and device id.
- Migration 050 creates `device_renames` plus indexes on
  `(client_id, platform, platform_device_id)` and `detected_at DESC`.
- Debug dashboard gains a `Recent device renames` card showing the
  last 300 detections.

### Notes
- Detection is idempotent — once a rename is recorded, the next run
  sees the new hostname on both sides of the comparison.
- Migration 050 also runs a one-time historical backfill comparing
  the latest two observations per key, so renames already in
  history (e.g., the All Data Health `0115Y25 → ADH-RE03` batch)
  register immediately after deploy.
- No findings, no alerts. Compliance state under the new hostname
  remains the source of truth. The Debug card is purely
  investigative.

## [0.29.0] — 2026-06-16

### Changed (semantic)
- `v_device_state_current.action_offline_platforms` now means
  **required + present + not currently online** rather than
  **stale required**. Previously a device with required Ninja+LogMeIn
  present but not actively checking in (last seen 14 days under a
  30-day threshold) showed empty `Online in` and empty `Offline`
  columns — the operator could not see where the device existed.
  Migration 049 broadens the definition to surface those platforms.
- For `Missing` state, the `Issue` text now appends
  `; offline in <platforms>` when other required platforms are
  present but not actively checking in. Operators viewing a device
  like `0115Y25` (missing SentinelOne, Ninja+LogMeIn present but
  offline) now read
  `Missing SentinelOne; offline in Ninja, LogMeIn` instead of
  just `Missing SentinelOne`.
- Side effect: devices with all required platforms present but one
  not currently checking in will now classify as `Offline` state
  instead of `Compliant`. This matches operator intuition (the
  agent isn't actively reporting) and the staleness-based alerting
  is unaffected — alerts still gate on Python's
  `stale_required_platforms` (over-threshold), not the broadened
  view.

## [0.28.3] — 2026-06-16

### Changed
- Promoted `Needs attention by customer` and `Needs attention by OS
  family` to full-width (24w) on both Today and Devices so the
  6-column tables (label + Missing/Offline/Stale/Review/Total) fit
  without horizontal scroll. Column widths restored to comfortable
  values (label 280, numeric 110).
- `Needs attention by issue type` + `Needs attention by device type`
  now share the row below at 12w each.
- Today rows below shifted down 6: Top device issues 20→26,
  Customer names review + Health problems 28→34.
- Devices section headers shifted: Platform gaps 24→30, Stale and
  ignored 38→44, All devices 50→56. Cards in those sections moved
  to match.

## [0.28.2] — 2026-06-16

### Changed
- Further trimmed the `Needs attention by customer` and `Needs
  attention by OS family` cards to remove horizontal scroll at the
  12-wide grid. Customer label 160→140, OS family label 180→160,
  numeric columns 80→65. Both cards now total well under 500px.

## [0.28.1] — 2026-06-16

### Changed
- Narrowed the first column on `Needs attention by customer`
  (Customer 220→160) and `Needs attention by OS family` (OS family
  220→180) on both Today and Devices. Numeric columns unchanged.

## [0.28.0] — 2026-06-16

### Changed
- Breakdown cards (Today + Devices, Customer / OS family / Device type)
  now read from `v_device_state_current` and show columns
  `Missing | Offline | Stale | Review | Total`. `Review` broadened to
  `device_state = 'Review' OR needs_review` so cross-customer
  ambiguity surfaces. Other state filters exclude `needs_review` rows
  so each device is counted exactly once across the row.
- `Needs attention by issue type` (Today + Devices) collapsed to a
  single `Devices` count. The row label already encodes the state, so
  per-state columns were noise. Added `No recent activity` (Stale) and
  split out `Missing — needs cross-customer review`.
- Scope on all four breakdowns extended to
  `device_state IN ('Missing','Offline','Stale','Review') AND NOT
  ignored` so the visible totals reconcile.
- Devices dashboard card key `devices_missing_by_customer` renamed to
  `devices_attention_by_customer` to match the column structure.
- Alerts dashboard `Finding type` filter now uses operator-facing
  labels (`Missing`, `Offline`, `Collector failed`) instead of raw
  finding_type strings, and dropped the dead `cross_client_conflict`
  value. Card WHERE clauses translate via CASE.
- Devices dashboard `NO AV` filter renamed to `S1 exempt` (label
  only; underlying logic unchanged).

## [0.27.3] — 2026-06-16

### Fixed
- Migration 048 still failed after v0.27.2 with
  `cannot change name of view column "rule_id" to "confirmed_gap"`.
  v0.27.2 refreshed `v_active_findings` so it picks up the new
  `confirmed_gap` column at the end, but the downstream
  `v_notification_queue` (from migration 039) selects `a.*` from
  `v_active_findings` and was being updated via CREATE OR REPLACE.
  Since `a.*` now expands one column wider, every column after that
  shifts right by one — including `rule_id`, which collides with the
  new `confirmed_gap` in the same slot. CREATE OR REPLACE does not
  allow column-name swaps. Added `DROP VIEW IF EXISTS
  v_notification_queue` before the recreate.

## [0.27.2] — 2026-06-16

### Fixed
- Migration 048 was failing on the deployed DB with
  `column f.confirmed_gap does not exist`. `v_active_findings` was
  defined in migration 035 with `SELECT f.*`; PostgreSQL froze the
  view's column list at CREATE time, so migration 045's
  `ALTER TABLE compliance_findings ADD COLUMN confirmed_gap` never
  propagated into the view. Added a `CREATE OR REPLACE VIEW
  v_active_findings` step at the top of migration 048 — re-expanding
  `f.*` picks up the new column (PostgreSQL allows columns added at
  the end). Downstream views in 048 can now reference
  `f.confirmed_gap`.

## [0.27.1] — 2026-06-16

### Changed
- Made Agent Compliance `Offline` findings alertable when the device is
  still active/recent somewhere else.
- Kept fully `Stale` devices out of alert readiness.
- Updated notification readiness views so Metabase shows the same
  confirmed alertable findings that the sender will actually process.
- Updated alert-facing wording from stale platform to offline platform.

## [0.27.0] — 2026-06-16

### Added
- Added the Agent Compliance human device-state model:
  `Compliant`, `Missing`, `Offline`, `Stale`, `Review`, and `Ignored`.
- Added `ninja_agent_compliance.v_device_state_current` as the clean
  reporting contract for device state, reason, recommended action,
  missing platforms, offline platforms, active platforms, and
  cross-customer review evidence.
- Added `ninja_agent_compliance.v_device_platform_detail_current` for
  the device drilldown, with one row per platform instead of only an
  aggregate device row.
- Added `ninja_agent_compliance.human_decisions` and the `Confirm
  missing` action path for cross-customer review cases.
- Added `Offline platform` as a Devices dashboard filter.

### Changed
- Reworked active Agent Compliance dashboard cards from `Fix now`
  wording to the new state model.
- Cross-customer same-name cases remain `Missing`, but now carry
  review evidence instead of being treated as fully confirmed.
- Missing-platform alerts no longer treat cross-customer ambiguity as
  confirmed unless an operator records a confirm-missing/not-same-device
  decision.

## [0.26.3] — 2026-06-15

### Fixed
- Fixed the Today `Compliant %` card to use columns exposed by
  `v_all_devices_human`. The formula still excludes stale and ignored
  devices from the denominator.
- Added a first-row `Compliant devices` KPI next to `Compliant %` so
  operators can see both the raw count and the percentage.

## [0.26.2] — 2026-06-15

### Changed
- Agent Compliance Today KPI row now separates `Stale` from compliance:
  first row is `Total devices`, `Compliant %`, `Fix now`, `Review`,
  and `Stale`.
- `Compliant %` is now calculated as compliant non-stale, non-ignored
  devices divided by all non-stale, non-ignored devices, so stale/offline
  and ignored/decommission candidates do not pull down platform coverage
  compliance.

## [0.26.1] — 2026-06-15

### Changed
- Device drilldown current-state table now expands by normalized device
  identity, so cross-customer missing-platform cases show both the
  selected customer row and the matching row found under another
  customer.
- Cross-customer collisions stay out of the primary device workflow
  unless the same missing platform is also observed under another
  customer for the same normalized device name.
- Device-facing work queue and human device view now surface only the
  actionable cross-customer case; generic same-name collisions remain
  in debug/customer summaries.
- Agent Compliance Today top KPIs now use a two-row layout so the
  seven required summary cards are readable. Long labels were shortened:
  `First notifications ready` is now `Ready to notify`, and
  `Collection problems` is now `Collection issues`.
- Cross-customer actionable issue text now says `found under another
  customer` so the operator sees the missing-platform condition instead
  of reading the same-name collision as the issue.

## [0.26.0] — 2026-06-15

### Added
- Review digest: daily cron job that rolls all current Review-class
  findings (`confirmed_gap = false` on missing / stale required
  platform) into one notification delivered via a new `review_digest`
  notification route. Distinct from the first-success per-finding
  alerts in `alerts.py` so judgment-call work gets one summary
  instead of being paged.
- New module `ingest.agent_compliance.review_digest` with
  `send_review_digest(now)`.
- New scheduled job `agent_compliance_review_digest` (cron, daily at
  `AGENT_COMPLIANCE_REVIEW_DIGEST_HOUR` UTC, default 08).
- New endpoint `POST /run/agent-compliance-review-digest` for manual
  trigger / testing.
- Migration 046 seeds the `review_digest` row in
  `notification_routes` (disabled by default; turn on once
  `AGENT_COMPLIANCE_REVIEW_DIGEST_WEBHOOK_URL` is set on the host).
- Settings: `AGENT_COMPLIANCE_REVIEW_DIGEST_ENABLED`,
  `AGENT_COMPLIANCE_REVIEW_DIGEST_HOUR`, and the matching env-var ref
  for the webhook URL.

### Notes
- Digest payload includes `total_open`, breakdowns by customer and
  finding type, and up to 100 sample items. Delivery is recorded in
  `alert_events` with `event_type='review_digest'` and a synthetic
  finding signature `review_digest:YYYY-MM-DDTHH` so it lives
  alongside per-finding events on the Alerts dashboard.

## [0.25.1] — 2026-06-15

### Changed
- Today KPI strip split: `Devices to fix` (Fix now + Review) → `Fix now`
  + `Review` as two separate scalar tiles. All seven KPIs now sit in
  one row at 3-wide each. Breakdowns scope to Fix now only (matches
  the alert gating shipped in v0.25.0).
- Dropped `LIMIT 5` from all four breakdown cards on both Today and
  Devices (Customer / Issue type / OS family / Device type). Each
  card now reconciles to the `Fix now` KPI total; long breakdowns
  scroll within the card.

## [0.25.0] — 2026-06-15

### Changed (behavioral)
- Alerts now fire only on **confirmed gaps**. A `missing_required_platform`
  finding is confirmed when either: the device has at least one online
  platform somewhere, OR the missing platform is observed under the
  same normalized hostname for a different customer (the Fix-now
  conditions). Review-state findings (missing but device fully offline)
  no longer trigger alerts.
- `stale_required_platform` findings never fire alerts. They are
  intended for a forthcoming daily Review digest (Phase 2).
- `source_failure` findings remain alertable (operational, not a
  judgment call).

### Added
- `confirmed_gap` boolean column on `compliance_findings` (migration
  045), set at emission time in `_findings_for_matrix` and
  `_source_failure_findings`. New per-(run_id, status, confirmed_gap)
  index supports the alert filter.
- `alerts.process_alerts` adds `AND f.confirmed_gap` to its SELECT.

### Notes
- The `compliance_matrix_current.cross_client_conflict` boolean and
  `v_cross_client_conflicts` debug surface stay as-is.
- Existing finding rows default `confirmed_gap` to false; the next
  collection or evaluate-only run re-emits with the correct flag.

## [0.24.1] — 2026-06-15

### Added
- `os_family` derived column on `v_device_work_queue` and
  `v_all_devices_human` (migration 044). Buckets Windows 7/8/8.1/10/11
  and Windows Server 2008-2025 by ILIKE on `os_name`; "Windows (other)"
  / "Windows Server (other)" / "Unknown" / "Other" cover the long
  tail.
- Two new Devices dashboard parameters: `OS family` and `Device type`
  (Workstation / Server). Wired into the Fix-now queue and All devices
  tables.
- "OS / Type" column on the Fix-now queue, All devices table, and
  Today's Top device issues card. Abbreviated form (`Win 11 · WS`,
  `Srv 2022 · SRV`).
- Two new breakdown cards on both Today and Devices:
  `Fix now by OS family` and `Fix now by device type`. Layout is now
  a 2x2 grid of breakdowns under the KPI strip / Fix-now queue.

### Changed
- Today rows shifted: `Top device issues` 10→16; `Customer names
  needing review` and `Collection and delivery problems` 18→24.
- Devices section headers shifted: Platform gaps 18→24; Stale and
  ignored 32→38; All devices 44→50. Cards in those sections moved to
  match.

## [0.24.0] — 2026-06-15

### Added
- Today dashboard: two top-5 cards — `Fix now by customer` and
  `Fix now by issue type` — placed between the KPI strip and the
  `Top device issues` table. Each row click opens the Devices dashboard
  pre-filtered (`state=Fix now` plus customer or platform where
  applicable).
- Devices dashboard: same two breakdown cards placed in the gap
  between the `Fix now` queue and the `Platform gaps` section. They
  respect the dashboard's `Customer` filter and click-set state /
  customer on the same page so they act as in-page filter chips.

### Changed
- Today dashboard rows shifted: `Top device issues` moves from row 4
  to row 10; `Customer names needing review` and `Collection and
  delivery problems` move from row 12 to row 18.

## [0.23.9] — 2026-06-15

### Fixed
- Migration 041 (v0.23.6) and migration 042 (v0.23.7) both failed on
  the deployed DB with
  `column "cross_customer_actionable_platforms" does not exist`. The
  CASE expressions in the same SELECT list referenced a sibling column
  alias, which PostgreSQL does not allow. Container was crash-looping
  on startup.
- Reverted migration 041 to the original demote-only definition shipped
  by v0.23.5 (1372a37). Migration 041 now applies cleanly.
- Rewrote migration 042 with a `with_actionable` CTE so the work-state
  CASE references the column from a parent CTE, not a sibling alias.
- Appended `cross_customer_actionable_platforms` at the END of both
  view column lists so `CREATE OR REPLACE` is compatible with the
  prior column order.

## [0.23.8] — 2026-06-15

### Fixed
- `Device appears under more than one customer` no longer appears as an
  Issue / Notification finding. v0.23.5/v0.23.6 demoted the case in the
  device work queue, but the underlying `cross_client_conflict` finding
  was still emitted by the Python evaluator, surfacing the noise in
  `v_active_findings` and the Issues / Notifications Metabase cards.

### Removed
- `_findings_for_matrix` no longer emits `cross_client_conflict`
  findings. The actionable cross-customer case is covered by the
  existing `missing_required_platform` finding plus the work-queue
  promotion shipped in v0.23.6.

### Changed
- Added migration
  `043_agent_compliance_disable_cross_client_conflict_rule.sql` that
  disables the `cross_client_conflict` row in `alert_rules` so a route
  accidentally enabled on it cannot fire. The row is left in place.

### Preserved (debug surface)
- The `cross_client_conflict` boolean on
  `compliance_matrix_current` and the `v_cross_client_conflicts` view
  remain untouched.
- Customer / debug Metabase cards that surface raw cross-customer name
  collisions remain unchanged.
- Metabase CASE branches that label historical
  `cross_client_conflict` alert events stay so the alert-history table
  still renders a human label.

## [0.23.7] — 2026-06-15

### Fixed
- Restored the shorter `online in` wording on the device work-queue and
  all-devices views. Migration 041 rebuilt the views from an older copy
  and reintroduced `seen online in`, undoing migration 040 (v0.23.2).

### Changed
- Cross-customer actionable issue text now reads
  `Missing <platforms>; same name under another customer` (dropped
  `seen`) for vocabulary consistency with the rest of the workflow.
- Added migration
  `042_agent_compliance_restore_online_in_wording.sql`.

### Removed
- `AGENT_COMPLIANCE_ALERT_COOLDOWN_HOURS` setting and the matching line
  in `.env.example` (unused since first-success alert dispatch landed
  in v0.23.1).
- Dead `_get_state` helper in `ingest/agent_compliance/alerts.py`.

## [0.23.6] — 2026-06-15

### Changed
- Cross-customer name collisions are promoted back into the device
  work queue (`Fix now`) only for the actionable case: the same device
  name is missing a required platform under one customer while that
  platform is observed under another customer.
- The general cross-customer collision summary remains in the
  customer/debug view and is not treated as a device fix item.
- The work-queue issue text for the actionable case reads
  `Missing <platforms>; same name seen under another customer`.
- Refined migration
  `041_agent_compliance_demote_cross_client_conflicts.sql` view
  definitions.

## [0.23.5] — 2026-06-15

### Changed
- Cross-customer name collisions were removed from the primary device
  work queue and all-devices human view.
- The customer/debug collision summary remains available with platform
  detail.

## [0.23.4] — 2026-06-15

### Changed
- Renamed the cross-customer conflict card to `Same name across
  customers`.
- Added platform detail to the conflict card so operators can see
  which platforms reported the same name.

## [0.23.3] — 2026-06-15

### Changed
- Cross-customer conflict rows now roll up to one line per device and
  show the customer list plus the platforms seen.
- Device drilldown now works with `host` alone; `customer` is optional
  so conflict rows can open a full multi-customer view.

## [0.23.2] — 2026-06-15

### Changed
- Shortened Agent Compliance device wording from `Seen online in` to
  `Online in` across the Today and Devices dashboards.
- Updated the device work-queue issue sentence from `seen online in`
  to `online in` via migration
  `040_agent_compliance_online_in_wording.sql`.

## [0.23.1] — 2026-06-15

### Changed
- Agent Compliance alert delivery is now first-success only: a finding
  signature sends at most once after a successful delivery.
- Failed notification delivery remains retryable on later evaluations
  until one delivery succeeds.
- Alert dispatch now runs after evaluation, including scheduled
  evaluate-only refreshes and configuration-triggered refreshes.
- Added a 30-minute evaluate-only scheduler via
  `AGENT_COMPLIANCE_EVALUATE_SCHEDULE_MINUTES`.
- Added an Agent Compliance job lock so collection and evaluate-only
  runs do not write the compliance matrix at the same time.
- Updated notification queue views and dashboard wording to remove
  cooldown/repeat language from the active workflow.

## [0.23.0] — 2026-06-15

### Changed
- Split Agent Compliance into two operational paths:
  full collection still pulls vendor data, while evaluate-only refreshes
  the current compliance model from the latest stored observations.
- Added `POST /run/agent-compliance-evaluate` for quick compliance
  refreshes without calling Ninja, SentinelOne, LogMeIn, or
  ScreenConnect.
- Customer/alias/requirement/exclusion/stale-threshold/device-ignore
  dashboard actions now schedule an evaluate-only refresh so the
  dashboard reflects configuration changes without waiting for the next
  vendor collection cycle.
- Evaluate-only re-resolves latest observations against current aliases
  and customer config before rebuilding the compliance matrix.
- Device ignore actions now default to 30 days and open a small duration
  form instead of hard-coding a 90-day ignore from the table.
- Tightened table column widths on primary device and alert work queues,
  and removed low-value route detail from `Open issues not notifying`.

## [0.22.2] — 2026-06-15

### Changed
- The Today `Devices to fix` KPI now counts only active online/actionable
  work states: `Fix now` and `Review`.
- Stale-only devices remain visible on the Devices dashboard under stale
  maintenance, but no longer inflate the Today landing-page action count
  or top device preview.
- Simplified device workflow states to `Fix now`, `Review`, `Stale`,
  `Ignored`, and `Good`. Degraded agents, cross-customer conflicts, and
  unknown states now appear as issue text instead of separate workflow
  states.

## [0.22.1] — 2026-06-15

### Changed
- Reordered the Agent Compliance Today top cards for human triage:
  `Total devices`, `Compliant %`, `Devices to fix`,
  `Notifications ready`, `Names to review`, and `Collection problems`.
- Removed `Ignored devices` from the Today top row. Ignored devices
  remain visible and restorable on the Devices dashboard.

## [0.22.0] — 2026-06-14

### Changed
- Rebuilt Agent Compliance around Level 1 human operations queues:
  `v_device_work_queue`, `v_all_devices_human`,
  `v_notification_queue`, `v_notifications_ready`,
  `v_customer_name_queue`, `v_required_platforms_effective`,
  `v_customer_alert_setup`, `v_alert_rules_human`,
  `v_notification_routes_human`, and `v_system_health_queue`.
- Added a dedicated `Agent Compliance - Setup` dashboard and moved
  configuration work there: required platforms, customer alert setup,
  alert rules, notification routes, and source setup.
- Reworked `Agent Compliance - Alerts` so it starts with notification
  operations, not config. The primary tables are now `Notifications
  ready to send`, `Open issues not notifying`, `Recently notified`, and
  `Open device issues`.
- Reworked `Agent Compliance - Devices` to read from the device work
  queue and use concise columns: customer, device, issue, seen online
  in, missing, last seen, state, and action.
- Reworked `Agent Compliance - Customers` to focus only on customer
  names and aliases: customer directory, names to review, platform names,
  and ignored customer names.
- Reworked `Agent Compliance - Health` to answer whether the data is
  trustworthy: collection/delivery problems, source status, current
  device gaps, and names needing review by platform.
- Renamed human-facing alert concepts: the old `Would fire on next run`
  concept is now `Notifications ready to send`, and active finding
  review is presented as `Open device issues`.
- New device ignore and bulk stale-ignore actions now default to a
  90-day expiry while remaining reversible from the dashboard.

## [0.21.10] — 2026-06-14

### Fixed
- Agent Compliance active alert/finding counts no longer use the raw
  append-only finding history. Migration
  `035_current_active_findings.sql` changes `v_active_findings` to keep
  only the latest row per finding signature with suppressions applied.
- Migration `036_cleanup_duplicate_findings.sql` deletes old
  unreferenced duplicate finding rows and marks older active rows
  resolved.
- Future agent-compliance runs now close the previous active finding
  snapshot before inserting the new current snapshot, preventing the
  historical active-count problem from returning.
- The Today KPI now says `Current findings` instead of `Active alerts`;
  alert delivery remains represented by `Would fire on next run`.

## [0.21.9] — 2026-06-13

### Changed
- Replaced `Required coverage` combo buttons with one column per
  platform: `Ninja`, `SentinelOne`, `LogMeIn`, and `ScreenConnect`.
  Each column shows `On` or `Off` and clicking the cell flips only that
  one platform for that customer/scope.
- Added `/a/tp` / `toggle-platform-requirement` action. If no exact
  customer/scope override exists, it seeds the override from the
  currently effective requirement and then flips the selected platform.

## [0.21.8] — 2026-06-13

### Changed
- Reworked customer-name review so the primary queue has the full
  decision set in one row: approve as customer, alias to suggestion,
  manually choose alias target, or ignore.
- Removed the separate `Alias customer name` dashboard card to reduce
  clutter.
- Removed low-value `Source` columns from the customer-name dashboard
  tables.
- Added a small controlled manual-alias picker page from the review row
  so an operator can choose any existing customer without exposing raw
  SQL or adding a cross-joined dashboard table.

## [0.21.7] — 2026-06-12

### Changed
- Customer name review now exposes the alias workflow. The review card
  shows a suggested customer when one can be inferred, and a new
  `Alias customer name` card lets the operator map any reviewed name to
  any existing customer using dashboard filters.
- Alias promotion now works against the enabled customer list directly
  instead of requiring the target customer to have a current alignment
  row.

## [0.21.6] — 2026-06-12

### Changed
- Agent Compliance alert dashboards now present platform-specific
  human labels such as `SentinelOne missing` and `LogMeIn stale`
  instead of showing the generic internal finding type.
- Added an `Alert rules` card to the Agent Compliance Alerts dashboard
  showing rule state, route state, severity, cooldown, customer scope,
  and device scope.
- Added dashboard action links to turn individual alert rules on or
  off through the existing ingest action endpoint pattern.
- Added `Customer alert setup` on the Alerts dashboard. It creates or
  updates customer-scoped alert rules so device alerts can be enabled
  per customer and per alert type.
- Added migration `034_customer_opt_in_device_alerts.sql`, which turns
  off global device-alert rules. Source/system alert rules are left
  alone. This makes device alerting opt-in by customer instead of
  enabled by default with suppressions.
- The Health dashboard `Missing by platform` count now excludes ignored
  devices, excluded customer names, and SentinelOne `NO AV` exemptions.
- Added `All current devices` at the bottom of the Devices dashboard as
  the manual-filter escape hatch. Metabase does not support a reliable
  dashboard-card collapsed-by-default state through the API, so the
  card is placed last under `Full device list`.

## [0.21.5] — 2026-06-12

### Fixed
- `Need action` on the Agent Compliance Devices dashboard no longer
  uses `ARRAY[{{missing}}]` / `ARRAY[{{online_in}}]` filter syntax.
  Those multi-select predicates could render invalid SQL in Metabase
  with `syntax error at or near "]"`. The card now uses
  `EXISTS ... IN ({{filter}})` predicates instead.

## [0.21.4] — 2026-06-12

### Fixed
- `Customer names to review` no longer shows names that already map to
  an enabled customer or enabled customer alias. Migration
  `033_filter_accepted_org_candidates.sql` closes stale open
  candidate rows as `promoted` and makes
  `v_org_candidates_current` filter accepted names defensively.

## [0.21.3] — 2026-06-12

### Changed
- Agent Compliance customer discovery now accepts Ninja-observed
  customer names automatically. Accepted rows use `clients.source =
  'ninja'` and notes that explain the logic: Ninja is authoritative
  for customer names, while non-Ninja platform names auto-alias only
  when their normalized name matches exactly.
- Fuzzy/prefix platform-name absorption no longer auto-aliases into a
  Ninja customer. Those cases remain in the customer-name review queue
  for an operator decision.

## [0.21.2] — 2026-06-12

### Added
- Migration `032_retry_clean_reset_by_name.sql` — idempotent retry of
  the corrected name-based reset for hosts where `031` is already
  recorded as applied. It re-clears Agent Compliance runtime state,
  identifies ghost-seeded clients from the current DB, deletes
  dependent aliases/requirements/sources/suppressions/rules, then
  deletes the ghost clients.

### Notes
- This migration tolerates partial manual cleanup. If the manual SQL
  already removed some rows, those deletes simply affect zero rows.
- A fresh `/run/agent-compliance` is required after deploy because the
  migration intentionally clears current runtime state again.

## [0.21.1] — 2026-06-12

### Added
- Migration `031_clean_reset_by_name.sql` — completes migration 030 by
  deleting "ghost-seeded" clients that pre-v0.16.4 dynamic discovery
  inserted without setting `source` explicitly. Those rows inherited
  the column DEFAULT of `'seed'` and survived migration 030's
  source-flag filter. Migration 031 cleans up by explicit name list
  matching the migration 019 PS seed.

### Fixed
- `031_clean_reset_by_name.sql` now re-truncates compliance runtime
  state before deleting ghost-seeded clients. This handles the live
  failure where a scheduled discovery run repopulated
  `org_alignment_current` between migration 030 and 031, leaving FK
  references to clients that 031 needed to delete.

## [0.21.0] — 2026-06-12

### Added
- Migration `030_clean_reset.sql` — wipes compliance state and
  dynamic-discovery cruft while preserving the PowerShell-derived
  seed (`source='seed'`) and operator-manual rows (`source='manual'`).

### Notes
- This is a destructive migration applied at the next ingest start.
  All compliance matrix history, findings, alert state, alert events,
  alignment history, platform observations, source runs, and
  org_candidates are truncated.
- All dynamic-discovery clients (Bobov45, Glas, D Miller Books,
  Silk Edge, Silvercup, Ready, TSK, plus collision-duplicates GGI,
  BH, City Painting (CPS), Trimworx-Deco-BGG, and any other
  alignment-source rows) are deleted. Their observations will
  surface them in the review queue on next run for explicit
  operator triage.
- All PowerShell-derived canonicals, aliases, requirements, and
  org_excludes from migrations 019/021/029 are untouched.
- Per-customer ScreenConnect `platform_sources` rows tied to
  deleted dynamic clients are also removed.
- Commit: `TBD`
- Deploy sequence:
  ```
  cd /amr-ch-01_data/ninja-dashboard && git pull
  docker compose up -d ingest
  curl -fsS -X POST http://127.0.0.1:8090/run/agent-compliance
  curl -fsS -X POST http://127.0.0.1:8090/bootstrap-metabase
  ```

## [0.20.0] — 2026-06-12

### Added
- **`Active alerts` KPI on Today** — count of unsuppressed active
  findings (`v_active_findings`) with click-through to the new
  Alerts dashboard.
- **`Agent Compliance — Alerts` dashboard** in the top nav,
  organized into three sections with filters for Customer, Severity,
  and Finding type:
  - **Would fire on next run** — preview that mirrors the
    `alerts.py` dispatcher logic: shows only findings whose route is
    enabled, a rule matches, and the dedup state would resolve to
    `new` / `changed` / `repeat-due` (i.e. not in cooldown).
  - **Active findings** — every unsuppressed active finding joined
    to `alert_state` so first-seen, last-seen, last-alerted-at, and
    repeat-count are visible.
  - **Recent deliveries** — the last 100 `alert_events` rows with
    status, response code, route, and the underlying finding.

### Notes
- No schema migrations.
- Today KPI widths compressed from 5- to 4-wide to fit the sixth
  scalar without overflow.
- Commit: `TBD`

## [0.19.0] — 2026-06-11

### Added
- **Devices dashboard reorganized into Triage / Gap analysis /
  Maintenance sections** with markdown dividers between groups, so
  the scope of the top filters is visible at a glance. Customer
  filter now applies to every card on Devices (including
  `Stale by customer` and `Ignored`).
- **Per-device drilldown dashboard** scoped to one `(customer, host)`
  pair. Accessible via row click on the `Device` column in
  `Need action`, `Active platform gap details`, and `Ignored`.
  Surfaces four history slices: per-run state from
  `compliance_matrix_history`, findings history, alert deliveries
  joined to `notification_routes`, and ignore history.
- **NO AV filter on Devices** (Yes / No) with the s1-exempt override
  semantics: by default exempt devices stay hidden from
  S1-missing-gap counts; selecting `Yes` reveals them.
- **Per-customer max age days from the UI** — `Required coverage`
  card on Customers gets `Age 7d` / `Age 30d` / `Age 90d` preset
  columns. `/agent-compliance/action/set-max-age` (short `/a/sd`)
  changes `max_age_days` independently from the platform combo so
  age and combo can be tuned separately.
- **Device drilldown click-through** from `Ignored` row → opens the
  drilldown scoped to that device.
- **New-customer candidates on Today** — a small table listing the
  most recent unresolved candidate names (platform, source, last
  seen) with a `Review` action that opens the Customers dashboard.
  The count-only KPI is preserved.

### Changed
- `Need action` now sources from `compliance_matrix_current` with
  inline suppression handling and includes degraded-but-compliant
  rows. Previously it sourced from `v_remediation_candidates`
  (strict noncompliant) which made the `State = Degraded` filter a
  no-op. PowerShell parity: degraded rows belong in the operator
  queue.
- Cross-customer conflict view (`Same device under multiple
  customers`) demoted from Customers to Debug. It's a data-quality
  signal, not a daily operator concern.

### Fixed
- **`s1_exempt` was always false.** The Ninja collector probed
  raw_data keys `policy`, `rolePolicy`, `rolePolicyName` — none of
  which exist on the `/v2/devices-detailed` response. Now joins to
  `ninja_core.policies` for both the assigned policy and the role
  policy and checks each name for `NO AV` (case-insensitive).
  The tags-array check is preserved. Devices flip on the next
  `/run/agent-compliance` cycle.
- `/a/*` short-path links from Metabase no longer 404. The `do_GET`
  router previously only matched the long
  `/agent-compliance/action/` prefix.

### Notes
- Renamed the `AV` / `AV exempt` column and filter to `NO AV` so it
  matches the Ninja tag/policy convention operators already know.
- No schema migrations beyond what's already applied.
- Commit: `TBD`

## [0.18.0] — 2026-06-11

### Added
- Agent Compliance Devices dashboard is now scenario-explorable. Four
  top-level filters (Customer, Missing platform, Online in, State) wire
  through the operator-facing cards on a per-card basis:
  - `Need action` consumes Customer + State.
  - `Missing but online elsewhere`, `Active gaps by missing platform`,
    and `Active platform gap details` consume Customer + Missing +
    Online in (and Missing only, for the bar chart).
- Drill-through on the two summary cards re-opens the same dashboard
  with the row's Missing / Online in values pre-applied as filter
  values — the count card is now actionable.
- `Stale devices by customer` table with a `Bulk ignore` action. One
  click suppresses every stale device under one customer; active
  missing-agent findings are never touched.
- `/agent-compliance/action/bulk-ignore-stale` (short alias `/a/bs`)
  for the bulk path. Single-customer, stale-only, guarded by the same
  `WHERE enabled` partial-index conflict path the single-row ignore
  already uses.
- Cumulative operator-UI rebuild since v0.17.5: rebuilt Devices /
  Customers / Health / Debug dashboard surface, humanized labels,
  customer mapping + coverage workflows, dashboard nav simplification,
  per-row action links to add-alias / exclude-org / approve-customer /
  ignore-device / restore-device / set-requirement, and the
  `AGENT_COMPLIANCE_ACTION_BASE_URL` config that lets the browser hit
  the loopback action endpoints when Metabase and ingest live on the
  same host.

### Fixed
- `/a/*` short-path links from Metabase no longer 404. The `do_GET`
  router was only dispatching `/agent-compliance/action/` paths; the
  inner alias map (`/a/aa`, `/a/ac`, `/a/eo`, `/a/sr`, `/a/ue`,
  `/a/ig`, `/a/ui`, and the new `/a/bs`) is now reachable.
- Logs no longer leak OAuth tokens or full request URLs.
- Seed orgs that produced bad canonical names are now demoted instead
  of cluttering the customer-review queue.
- Ingest service port is now published on the loopback so the
  in-browser action links resolve against the same host as Metabase.

### Notes
- Apply through migration `026_alert_suppressions_display_name.sql`
  before bootstrapping Metabase.
- Commit: `TBD`

## [0.17.5] — 2026-06-11

### Added
- Agent Compliance Org Review rows now include explicit action links
  for:
  - Add alias
  - Exclude org
- Added loopback operator endpoints in the ingest service to write
  promoted aliases and excludes back into Postgres.

### Fixed
- The operator review flow no longer stops at a read-only dashboard; it
  can now push approved alias/exclude changes into the DB-backed config.

### Notes
- Commit: `TBD`

## [0.17.4] — 2026-06-11

### Added
- Agent Compliance Metabase now provisions separate operator-facing
  dashboards for:
  - Command Center
  - Devices
  - Org Review
  - Source Health
  - Debug
- Top nav bars were added to the Agent Compliance dashboards so the
  operator can move between those views like the patching dashboards.
- Primary Agent Compliance tables now use humanized labels and concise
  columns instead of schema-style names.
- Added `AGENT_COMPLIANCE_OPERATOR_UI.md` and
  `AGENT_COMPLIANCE_ALERT_WORKFLOW.md` to define the dashboard and
  alert contract before further build-out.

### Fixed
- Debug/raw observation details are now isolated to the Debug dashboard
  instead of appearing in the primary operator view.
- Org review and source health work are separated from device-level
  remediation work to make the primary dashboard easier to navigate.

### Notes
- Commit: `TBD`

## [0.17.3] — 2026-06-10

### Added
- Migration `021_org_excludes.sql` with a DB-backed org-exclude list
  seeded to the original PowerShell values:
  - `abe private`
  - `amrose-test`

### Fixed
- `config_loader.py` now loads org excludes from Postgres instead of a
  hardcoded constant.
- `sync_clients_from_observations` now skips DB-backed excludes and uses
  alias-aware discovery to avoid duplicate canonical org creation for
  similar names/typos.
- The Metabase unresolved-observations card now filters out excluded org
  names so it stays focused on operator action items.

### Notes
- No schema migration is required for v0.17.3 beyond applying `021`.
- Commit: `TBD`

## [0.17.2] — 2026-06-05

### Fixed
- `compliance_matrix_current.is_compliant` no longer gates on
  `cross_client_conflict` or `is_stale`. This restores PowerShell
  parity with `Build-MultiOrgComplianceMatrix` line 1539
  (`$isCompliant = $missing.Count -eq 0`). Cross-org conflict remains
  an informational column and continues to generate its own finding;
  stale remains an independent column. The `not unknown` clause is
  retained as an intentional Python-side improvement for the
  continuous-collection model, where a transient source failure must
  not silently flip devices to non-compliant.
- Org alignment status now consults `client_aliases` (manual + seed)
  for the expected platform name before falling back to the observed
  routed name and finally to the client's display name. This matches
  the PowerShell `Get-OrgAlignmentMap` precedence (`$cfg.NinjaOrg` /
  `$cfg.S1Site` / `$cfg.LMIGroup` first, observed norms second,
  `$orgName` third). Aliases sourced from prior alignment runs are
  excluded to avoid feedback loops.

### Notes
- No schema migration is required for v0.17.2.
- Commit: `TBD`

## [0.17.1] — 2026-06-10

### Fixed
- Alignment persistence now uses the refreshed client lookup after new
  canonical orgs are inserted, so newly discovered orgs are written to
  `org_alignment_current` and `client_aliases`.

### Notes
- No schema migration is required for v0.17.1.
- Commit: `TBD`

## [0.17.0] — 2026-06-10

### Added
- Migration `020_agent_compliance_parity.sql`:
  - `org_alignment_current`;
  - `org_alignment_history`;
  - alignment views for current state and mismatches;
  - PowerShell parity columns on current/history compliance matrix.
- Persisted org alignment report fields:
  - `MATCHED` / `FUZZY` / `MISSING` / `NA` / `CONFIGURED`;
  - overall alignment status;
  - platform routing names;
  - merged-from details;
  - suggested config.
- Matrix parity fields:
  - org alignment status;
  - per-platform presence, online state, last seen, and device IDs;
  - S1 exemption;
  - degraded state.
- Agent Compliance dashboard cards for alignment mismatches and
  degraded devices.
- `AGENT_COMPLIANCE_V2_BLUEPRINT.md`.

### Changed
- Matrix `is_stale` now follows the PowerShell semantics: present on
  at least one platform and active on none.
- Matrix `is_degraded` now follows the PowerShell semantics:
  compliant, not stale, but at least one required-present platform is
  inactive.

### Notes
- This is the parity/schema pass before v2 architecture cleanup.
- Commit: `TBD`

## [0.16.4] — 2026-06-10

### Fixed
- Agent Compliance org alignment now persists PowerShell-style
  canonical platform aliases instead of treating every observed platform
  name as its own mapped client.
- Canonical org selection now follows the PowerShell priority:
  configured client, then Ninja name, then SentinelOne name, then
  LogMeIn name.
- Added the PowerShell fuzzy absorption guardrail: non-Ninja names can
  route to exactly one Ninja org when normalized names contain each
  other and platform sets are complementary.
- Alias loading now has deterministic precedence: manual, seed,
  alignment, then other.

### Notes
- No schema migration is required for v0.16.4.
- Commit: `TBD`

## [0.16.3] — 2026-06-10

### Fixed
- Agent Compliance org mapping now mirrors the PowerShell alignment
  model more closely:
  - observed Ninja orgs, SentinelOne sites, and LogMeIn groups are
    admitted as clients automatically unless excluded;
  - every client receives default Ninja org, SentinelOne site, and
    LogMeIn group aliases by client name;
  - explicit configured aliases still override/augment defaults.
- Preserved the original static excludes for `Abe Private` and
  `AMRose-Test`.

### Notes
- No schema migration is required for v0.16.3.
- Commit: `TBD`

## [0.16.2] — 2026-06-10

### Fixed
- LogMeIn group-map parsing now mirrors PowerShell's case-insensitive
  JSON property access for `hosts`, `groups`, group `id`/`name`, and
  host `groupid`.

### Added
- LogMeIn raw observation data now includes an `_agent_compliance`
  parser marker with `lmi_group_id`, `lmi_group_name_resolved`, and
  `lmi_group_map_size` for deployment verification.

### Notes
- No schema migration is required for v0.16.2.
- Commit: `TBD`

## [0.16.1] — 2026-06-10

### Fixed
- Agent Compliance migration parity:
  - LogMeIn now resolves host group names from the `/v2/hostswithgroups`
    `groups` map using host `groupid`/`groupId`.
  - LogMeIn now waits and retries once on HTTP `429` rate limits.
  - Client alias matching now includes normalized org/site/group names.
  - Hostname normalization now strips curly apostrophes.
  - Matrix building now applies conservative unique-prefix hostname
    matching for truncated hostnames.
  - Ninja `NO AV` tag/policy evidence now exempts devices from
    SentinelOne missing-agent findings.

### Added
- `AGENT_COMPLIANCE_MIGRATION_REVIEW.md` documenting migrated behavior,
  v0.16.1 parity fixes, and remaining intentional differences.

### Notes
- No schema migration is required for v0.16.1.
- Commit: `TBD`

## [0.16.0] — 2026-06-10

### Added
- **Agent Compliance v1 foundation** inside the existing
  `ninja-dashboard` stack. New `ninja_agent_compliance` schema covers
  DB-backed client/source/alias/requirement config, source runs,
  platform observations, current/history compliance matrix, findings,
  suppressions, alert state, and alert delivery events.
- **Multi-platform collection model**:
  - Ninja observations come from existing `ninja_core` tables.
  - SentinelOne, LogMeIn, and ScreenConnect have dedicated collectors.
  - ScreenConnect is modeled as many per-client tenant sources.
- **Source-health guardrail**: source failures are recorded as source
  findings and do not blindly turn every device into a missing-agent
  finding for that platform.
- **Alerting routes**: webhook, SMTP email, and Zendesk request
  delivery are available behind DB route config and `.env` settings.
  Alert state dedupes unchanged findings and respects cooldowns.
- **Separate scheduling** for agent compliance:
  `AGENT_COMPLIANCE_ENABLED` plus
  `AGENT_COMPLIANCE_SCHEDULE_HOURS`. Manual endpoint:
  `POST /run/agent-compliance`.
- **Agent Compliance Metabase collection/dashboard bootstrap** with
  first-pass KPI, source health, remediation, and active-finding cards.

### Changed
- Existing `/run` remains a patch/Ninja ingest trigger; explicit
  `POST /run/patches` was added for clarity.
- `run_log` stats now expose `run_id` to domain modules while keeping
  existing row-count behavior.

### Notes
- Agent compliance is disabled by default until source config and
  secrets are provisioned.
- Ninja health can enrich AV/security triage, but SentinelOne API
  remains the authoritative S1 compliance source.
- Commit: `TBD`

## [0.15.5] — 2026-06-08

### Removed (dead code, ~248 lines)
- `_PATCH_SCOPE_CTE` (~99 lines) — scope-derivation block, dead since
  migration 015 moved `patching_scope` into `v_active_devices` as an
  indexed column.
- `_device_compliance_scalar_query()` — superseded by
  `_patching_device_compliance_scalar_query()`.
- `_daily_patching_device_compliance_query()` — never wired into any
  Trends card; replaced by `_daily_device_compliance_query()`.
- `_sql_string_list()` + `ENABLED_POLICY_SQL` — orphans (only used
  by the removed `_PATCH_SCOPE_CTE`).
- `COLOR_OK_GREEN`, `PATCH_ACTIVITY_LABEL_P`,
  `_CMD_DEVICE_TYPE_FILTER`, `_OVERALL_DEVICE_TYPE_FILTER`,
  `_TRENDS_DEVICE_TYPE_FILTER`, `_ORG_FILTERS_PATCH_CS_NO_CLASS`,
  `_ORG_FILTERS_PATCH_CS_NO_OS` — back-compat aliases / unused
  filter variants.

### Added
- **Device Drilldown Device Summary** gains `Last Boot` column
  (from `device_snapshots.last_boot` via the existing `latest_snap`
  CTE).

### Notes
- Pure cleanup + one column add. No schema change, no migration,
  no behavior change.
- Commit: `TBD`

## [0.15.4] — 2026-06-07

### Changed
- **`issue_type` priority: warnings now rank above delayed patches**
  (migration 018, drop+recreate `device_troubleshooting_signal`).
  Operator feedback: delayed patches are normal (auto-approve window),
  warnings are operator-actionable. New branch
  `Stalled with warnings` inserted between `Stalled with manual
  approvals` and `Stalled with delayed patches`; mirror `Active with
  warnings` added between `Reboot pending` and `Manual approvals` in
  the active-path. `_ISSUE_TYPE_OPTIONS` updated to include the new
  values (plus the previously-missing "Stalled (install dates
  missing)" pair).

### Added
- **Issues drillthroughs from Warnings by Category / Failures by
  Error Code cards.** Click a category row → new
  `Devices Matching Warning Category (30d)` table populates with
  the specific devices generating that warning. Same for failures
  via `Devices Matching Failure Error Type (30d)`. Two new
  parameters: `p_issue_warning_cat` + `p_issue_failure_err`.
- **Org Overview `Top Problem Devices` table** — per-org triage
  view (mirrors Issues queue but scoped to the active org filter).
  Click device → Device Drilldown.
- **`Earliest Scan in DB` column** added to operator-facing tables
  where missing: Issues queue, Top Devices by Warnings/Failures,
  CC Failed Patch Queue, CC Manual + Delayed Patches, CC Patches
  Installed Awaiting Reboot. CC tables get a LEFT JOIN to
  `device_troubleshooting_signal` to pick up the column. Operator
  can now see "is this device's failure an old-history thing or a
  fresh-onboarding thing?" without leaving the table.

### Notes
- Migration 018 drop+recreates only `device_troubleshooting_signal`
  (no patch MV touches), so it's fast (~seconds).
- All dashboard additions are additive; no card removed.
- Commit: `TBD`

## [0.15.3] — 2026-06-07

### Added
- **Command Center row 7 — fleet pulse band:** three new scalars —
  `OS Patch Warnings (24h)`, `OS Patch Failures (24h)`, `Data
  Freshness`. Operator opening CC now sees both today's warning/-
  failure volume AND whether the numbers below are fresh, without
  drilling into Issues. Both activity scalars click-through to Issues.
- **Command Center `Ingest Pipeline Health` table** (bottom row) —
  per-domain last run status, started_at, rows inserted, duration,
  age, and error preview. Surfaces silent per-domain failures.
- **Issues row 3:** `Devices with Warnings (30d)` + `Devices with
  Failures (30d)` scalars to round out the 6-scalar device-state row.
- **Patch Detail `Patches by Type` pie** — companion to the Type
  column added in 0.15.2. Shows the in-scope patch category mix at
  a glance.
- **PCOV All Devices** gets `Earliest Scan in DB` column (matches
  Drilldown's rename, below). `_PCOV_CTE` extended to expose the
  underlying signal.

### Changed
- **Device Drilldown Device Summary**: `First Managed` column
  renamed to `Earliest Scan in DB`. The value is bounded by Ninja's
  ~90-day activity retention plus our backfill window — calling it
  "First Managed" implied a true onboarding date that the data
  can't honestly support.
- **Command Center layout**: tables shifted +3 rows to make room
  for the new row-7 scalar band. No card content changed.
- **Issues layout**: queue and below shifted +3 rows for the same
  reason. No card content changed.

### Notes
- Pure dashboard surface — no migration, no schema change, no
  ingest change.
- Deferred from this pass (low value or high complexity, parked):
  warning-category → device-list drillthrough (requires a new
  Metabase param + categorized device card); with-drivers vs.
  without-drivers compliance comparison (adds confusion, env-var
  toggle already does the job for ad-hoc).
- Commit: `TBD`

## [0.15.2] — 2026-06-07

### Added
- **PCOV `All Devices` table** gains `Last Scan`, `Warnings 30d`,
  `Failures 30d` columns (alongside the existing Last Install /
  Last Contact pair). Operator's "all devices, everything" sortable
  table now exposes the warning/failure signal so they can pivot
  without going to Issues. `_PCOV_CTE` extended to surface the
  underlying columns from `device_troubleshooting_signal`.
- **Patch Detail big table** gains a `Type` column (sourced from
  `current_patch_state.patch_category`). Operator filtering by KB
  or status can now see category alongside severity.
- **Trends dashboard**: two new bar cards.
  - `OS Patch Warnings per Day` — fleet-wide MESSAGE volume per day.
  - `OS Patch Operational Failures per Day` — distinct from the
    existing install-outcome failure trend; counts the
    `PATCH_MANAGEMENT_FAILURE` activity rows (service restart,
    timeouts, download errors) rather than install_outcome rows.
- **Org Overview**: per-org `OS Patch Warnings (30d)` and
  `OS Patch Failures (30d)` scalars. Per-client SLA review.
- **Issues dashboard**: `Top Devices by Warnings (30d)` and
  `Top Devices by Failures (30d)` tables. Companion to the
  by-category and by-error-code cards added in 0.15.1; tells the
  operator WHICH devices are responsible for the volume. Click-
  through to Device Drilldown.

### Notes
- All additive — no migration, no schema changes. Existing cards
  unchanged.
- Commit: `TBD`

## [0.15.1] — 2026-06-07

### Added
- **Per-device warning + failure + scan rollups on
  `device_activity_signal`** (migration 017). Three new column
  groups, all driven from existing activity rows so no re-ingest
  needed:
  - Warning rollup: `last_warning_at`, `warning_events`,
    `warning_events_30d`, `last_warning_message` — aggregates
    `PATCH_MANAGEMENT_MESSAGE` + `SOFTWARE_PATCH_MANAGEMENT_MESSAGE`
    rows per device.
  - Failure 30d window: `patch_failure_events_30d` joins the
    existing `patch_failure_events` lifetime count.
  - Scan rollup: `last_scan_started`, `last_scan_completed`,
    `first_scan_started`, `scan_events_30d` — answers "when did
    Ninja first / last scan this device?" without per-card
    aggregation.
  - All surfaced on `device_troubleshooting_signal` for
    Issues / Drilldown re-use.
- **Device Drilldown Device Summary** now shows `First Managed`,
  `Last Scan`, `Last Warning`, `Warnings (30d)`, `Failures (30d)`
  columns alongside the existing health/contact fields.
- **Device Drilldown `Recent OS Patch Warnings (30d)` table** —
  one row per warning event with a `Category` column that hand-
  classifies the 7 dominant message patterns we see in real data
  (outstanding approved patches, scheduled job skipped, metered
  connection, post-reboot scan required, OS patch download error,
  reboot needed, WUA out of date) plus `Other` / `Reboot
  scheduling` / `Download complete` buckets.
- **Device Drilldown `Recent OS Patch Failures (30d)` table** —
  same shape, classified by Ninja error code (-3005 / -3004 /
  -1001) plus common service-level signatures.
- **Issues `Issue Queue` table** gains `Warnings 30d`,
  `Failures 30d`, and `Days Since Warning` columns. Sort order
  now bumps devices with active warnings or failures above
  manual approvals.
- **Issues `Warnings by Category (30d)` card** — fleet-wide
  table of warning events grouped by category, with device count
  per category. Respects the dashboard org filter.
- **Issues `Failures by Error Code (30d)` card** — same shape
  for failures.

### Notes
- Migration 017 drop+recreates both `device_activity_signal` and
  the dependent `device_troubleshooting_signal` (full body
  duplicated from migration 016 with new columns added). Same
  refresh strategy as before — no `main.py` changes needed.
- Category classification lives in dashboard SQL (CASE WHEN over
  message text), not in the MV. Tweaking categories doesn't
  require a migration.
- Commit: `TBD`

## [0.15.0] — 2026-06-05

### Fixed
- **Never-Patched misclassification for devices with install rows but
  no `installedAt`.** Ninja's `/queries/os-patch-installs` omits the
  install timestamp for ~1.2% of INSTALLED rows (typically old or
  OS-applied historical patches). The `device_patch_signal`
  materialized view previously filtered `installed_at IS NOT NULL` at
  source, dropping ~6 devices from the signal entirely and showing
  them as Never-Patched even though Ninja has them as installed.
  Migration 016 rebuilds the view with two columns:
  `ever_installed bool` (existence-only) and `last_seen_at`
  (still strictly `MAX(installed_at)`). All 53 references to
  `dps.last_seen_at` in `metabase_bootstrap.py` keep working; the
  Never-Patched / Stalled / Actively-patching classification now
  reads `ever_installed`, so the affected devices reclassify into
  Stalled with `issue_type = 'Stalled (install dates missing)'`.

### Added
- **`DASHBOARD_PATCH_CATEGORIES_EXCLUDE` env var.** Comma-separated
  list of Ninja patch categories (`patch_facts.type` values) to hide
  from every patch-context dashboard query. Default
  `DRIVER_UPDATES`. Rendered into a shared `_PATCH_TYPE_EXCLUDE` SQL
  fragment at the top of `metabase_bootstrap.py` and appended to
  every patch CTE. Empty value disables the exclusion in one place.
  Raw rows stay in `patch_facts` — exclusion is presentation-only,
  so re-enabling drivers later is a one-line config change.
- **`patch_category` column** surfaced on the
  `current_patch_state` and `latest_install_outcome` materialized
  views (sourced from `patch_facts.type`). Device Drilldown's
  Patch State History and Install History tables now include a
  `Type` column. Operator-facing tables on Patch Detail / Command
  Center / Org Overview select the column too so it's available to
  Metabase via the underlying CTE.

### Notes
- Migration 016 drop+recreates `device_troubleshooting_signal` along
  with the three patch MVs (dependency order). The signal MV's
  `patch_status`, `issue_type`, and `suggested_action` CASE blocks
  were updated to read `ever_installed` and added explicit branches
  for the dateless-stalled subset.
- `ninja_observed_at` deliberately NOT used as a fallback install
  date. It's Ninja's scan timestamp, refreshed every ingest cycle,
  so treating it as install time would falsely classify devices Ninja
  keeps re-scanning ancient installs on as actively patching.
- Commit: `TBD`

## [0.14.11] — 2026-06-04

### Changed
- **Custom-field ingest now uses Ninja's scoped values feed.** The
  ingest switched from the legacy device-centric report to
  `/queries/scoped-custom-fields`, so organization and location
  custom fields now flow through the same pipeline as device fields.
- **The `.env` allowlist now feeds the API query itself.** If
  `INGEST_CUSTOM_FIELDS_INCLUDE` is set, the ingest passes that field
  list to Ninja and only stores the selected names. Pivoted
  `v_device_custom_fields`, `v_organization_custom_fields`, and
  `v_location_custom_fields` are regenerated from the scoped feed.
- Commit: `TBD`

## [0.14.10] — 2026-06-04

### Changed
- **Org Overview and Trends now use the patching-device denominator in
  the visible KPI titles.** The second operator KPI is now
  `Fully patched % (patching devices)` everywhere it appears on the
  org-facing and trend dashboards.
- Commit: `be63e7e`

## [0.14.9] — 2026-06-04

### Changed
- **The fully-patched KPI now states its real denominator.** The
  second operator KPI is now `Fully patched % (patching devices)`,
  which matches the formula: among devices that are actively
  patching, how many have no open missing patches.
- Commit: `148de4e`

## [0.14.8] — 2026-06-04

### Fixed
- **Command Center KPI bootstrap no longer crashes at import time.**
  The new `Actively patching %` helper now carries its own device
  classification CTE instead of referencing `_PCOV_CTE` before that
  symbol is defined.
- Commit: `ba55729`

## [0.14.7] — 2026-06-04

### Changed
- **Command Center now headlines active patching instead of compliance.**
  Kept the raw count cards, but the top-right KPI now reads
  `Actively patching %` so the landing page answers whether devices
  are getting patched right now.
- **Overall Status and Org Overview now show the two operator rates.**
  The left KPI is `Actively patching %`; the right KPI is
  `Fully patched devices %`.
- **Trend cards were realigned to the same operator split.**
  Trends now show `Fully patched devices % per Day` and `Patching
  Devices per Day` instead of the old compliance/progress wording.
- Commit: `52c22e6`

## [0.14.6] — 2026-06-04

### Changed
- **Patch KPI wording split into operator-facing labels.** Command
  Center now shows a single `Devices Compliant %` headline KPI.
  Overall Status and Org Overview now split the story into `Devices
  Compliant %` on the left and `Patch Progress %` on the right.
- **Detailed patch-progress cards renamed for clarity.** The
  highest-level org breakdowns now read `Clients with Lowest Patch
  Progress`, `Patch Progress by Device Type`, `Patch Progress by
  Operating System`, and `Client Patch Progress` instead of the
  ambiguous `Patch Compliance` wording.
- **Trends dashboard gained the same KPI pair.** Added daily trend
  cards for `Devices Compliant %` and `Patch Progress %` so operators
  can see direction, not just a single static score.
- Commit: `fafe234`

## [0.14.5] — 2026-06-04

### Added
- **Device Summary now shows current reachability next to `Last Contact`.**
  Added an `Online?` column derived from the latest snapshot's
  `offline` flag, rendered as `Yes` / `No` / `Unknown`. This makes the
  difference between "recently contacted" and "currently reachable"
  explicit in the device detail view.
- Commit: `fdaca32`

## [0.14.4] — 2026-06-04

### Fixed
- **Metabase cards now get a stable hidden identity instead of being
  matched by title alone.** The bootstrap was reusing cards by display
  name, and multiple dashboards intentionally share titles like
  `Active Devices`, `Current Patch State`, `Patching Devices`, and
  `Failed Patches`. That let later dashboards overwrite earlier card
  SQL / template-tag wiring.
- Resolution: each card now carries a hidden stable UID in
  `description` and `_upsert_card()` matches on that UID. Existing
  duplicate-title cards in Metabase are left alone; new bootstraps
  create or update the correct per-dashboard card object.
- Commit: `2779967`

## [0.14.3] — 2026-06-04

### Fixed
- **Device-card filters now reach every card on Command Center,
  Overall Patching Status, Org Overview, and Trends.** Bug pattern:
  cards declared more template tags than their dashcard
  `parameter_mappings` covered, and Metabase silently broke the
  binding for the mapped parameters too. Patch Detail (which has
  tags == mappings = 8) worked fine; the other dashboards' device
  cards declared the FULL tag set but mapped only a subset
  (skipping severity).
- Resolution: every card on these four dashboards now uses the
  `_*_PARAM_MAPPINGS_FULL` variant. Device cards have a severity
  mapping declared even though their SQL never references
  `{{severity}}` — Metabase handles that fine; the mapping exists
  but does nothing.

### Notes
- Per the blueprint-first rule: `BLUEPRINT.md` written with audit
  table comparing tags vs mappings per dashboard. Hypothesis
  confirmed by the pattern: every dashboard with a mismatch had
  the symptom; Patch Detail (matched) worked.
- Device Patching Status (PCOV) tags and mappings already match
  (5/5) yet user reports the same symptom. That's a separate
  investigation in v0.14.4 if this fix doesn't resolve it.

## [0.14.2] — 2026-06-04

### Added
- **Overall Patching Status filter set expanded** to Org · Device
  Type · OS Family · Severity (all multi-select). Previously only
  Device Type. Every Overall scalar / chart / table now honors
  every applicable filter.
- **Trends filter set expanded** to Days · Org · Device Type ·
  Severity (all multi-select except Days). Time-series cards
  narrow per the active scope.
- **Org dropdown converted to multi-select** on Patch Detail,
  Org Overview, and Device Patching Status. Operator can compare
  2-3 clients at once.

### Changed
- All Overall cards have a `JOIN ninja_core.organizations o`
  added where missing. Patch-context CTEs select `severity`.
- All Trends cards JOIN organizations. Patch-counting cards
  (installs/day, failures/day, manual-age) honor severity;
  device-population cards (reboots/day, active-devices/day) don't.
- Org SQL predicates everywhere changed from `o.name = {{var}}`
  to `o.name IN ({{var}})` so the multi-select substitution
  works.
- `build_overall_parameters` and `build_trends_parameters` now
  take `org_names` (Overall also takes `os_families`).

### Notes
- Compliance scalars on Overall (overall_compliance,
  compliance_worst, compliance_all) honor Org + Device Type + OS
  Family but NOT Severity. Compliance is intended to be the fleet-
  wide coverage number; scoping by severity would change its
  meaning to "% of Critical patches installed", which is a
  different metric. Defer until operator asks.

## [0.14.1] — 2026-06-04

### Added
- **Patch Command Center filter set expanded** to Org · Device
  Type · Severity (all multi-select). Previously only Device Type.
  Every card on Command Center now honors all three filters.
- New `PARAM_CMD_ORG`, `PARAM_CMD_SEV` parameter constants;
  `_CMD_TAGS` / `_CMD_PARAM_MAPPINGS` expanded; new filter
  fragments `_CMD_FILTER_ORG`, `_CMD_FILTER_SEV_CS`,
  `_CMD_FILTER_SEV_LIR` and combined `_CMD_FILTERS_DEVICE`,
  `_CMD_FILTERS_PATCH_CS`, `_CMD_FILTERS_PATCH_LIR` mirror the
  pattern established in Org Overview.

### Changed
- All Command Center scalar SQLs that previously joined just
  `ninja_core.devices` now also join `ninja_core.organizations` so
  the Org filter can bite.
- Patch-context scalar CTEs (`cmd_approved` / `_manual` /
  `_delayed` / `_failed`) now select `severity` so it can be
  filtered in the outer WHERE.
- `cmd_clients` table applies the severity filter at CTE-level
  (inside each `WITH ...` block) so the outer LEFT JOIN
  semantics are preserved — filtering severity in the outer
  WHERE would silently drop devices with no matching patch row.

### Notes
- Audit before changes (per blueprint): every Command Center card
  was already correctly wired for the Device Type filter
  (template_tags + param_mappings + filter in SQL). User-reported
  "filters don't apply" was most likely a stale Metabase state
  from before the v0.13.6 wiring deployed. Forcing a fresh
  bootstrap should resolve it.

### Process
- Followed the new blueprint-first rule. `BLUEPRINT.md` updated
  with the proposed filter set per dashboard; user confirmed
  before implementation.

## [0.14.0] — 2026-06-04

### Removed
- **Needs Reboot scalar** demoted from the top-row Devices group on
  Patch Command Center, Overall Patching Status, and Org Overview.
  In a patch-management context Reboot is an action signal, not a
  high-level KPI — operators look at Failed / Manual / Stalled /
  Never-Patched first. The `Devices Needing Reboot` *table* on
  Overall and Org stays — that's the action queue for actually
  rebooting devices. The `Needs Reboot` column on Command Center's
  "Clients Needing Attention" table also stays. The Trends
  dashboard's "System Reboots per Day" chart is unchanged.
- Devices rows reflowed from 5 tiles (5+5+5+5+4 = 24) to 4 tiles
  (6+6+6+6 = 24) on all three dashboards.
- Removed the three reboot keys (`cmd_reboot`, `overall_reboot`,
  `org_reboot`) from `_SCALAR_ALERT_RULES`.

### Fixed
- **Filter-reach audit (Shape A + Shape B) clean.** Tags-vs-
  fragments compared on every dashboard; no parameter declared
  without a matching SQL predicate (false positives in the audit
  script were nested dict keys and timeline-window params
  consumed directly by each card's CTE).
- Removed a duplicate `[[AND d.system_name = {{device}}]]` line
  that the v0.13.9 fix had accidentally added to
  `_FILTER_PREDICATES` (the predicate was already at the bottom
  of the fragment).

### Process
- Second task to follow the new blueprint-first rule
  (`BLUEPRINT.md` written, *planning* → *in progress* → *done*).
  Audit findings recorded in the blueprint before any code
  changes.

## [0.13.9] — 2026-06-04

### Fixed
- **Patch Detail filters now apply to every card.** Two gaps
  closed:
  1. **Device filter wasn't reaching any card.** The shared
     `_FILTER_PREDICATES` fragment declared all the other
     filters but not the Device one. Adding
     `[[AND d.system_name = {{device}}]]` so picking a device
     narrows the donut / severity bar / KB chart / tables.
  2. **`detail_installs_timeline` used the old single-select
     `= {{var}}` syntax.** It inlined its predicates instead of
     using `_FILTER_PREDICATES`, so it didn't pick up the v0.13.8
     multi-select conversion. Replaced the inlined block with
     `{_FILTER_PREDICATES}` + the days predicate. Multi-select on
     Status / Device Type / Severity / Install Results / OS now
     works on the timeline too.

## [0.13.8] — 2026-06-04

### Changed
- **Multi-select dashboard filters.** Operators can now pick
  several values at once on the most-used dropdowns. New
  `_param_multiselect` helper sets `isMultiSelect: True` on top
  of the existing dropdown shape; SQL predicates updated from
  `= {{var}}` to `IN ({{var}})` so single-value and multi-value
  both work. Applied to:
    - **Patch Detail**: Current Patch State, Device Type,
      Severity, Install Results, Operating System Family.
    - **Org Overview**: Device Type, OS Family, Severity.
    - **Device Patching Status**: Device Type, Operating System
      Family, Patching Status.
    - **Patch Command Center / Overall Patching Status /
      Trends**: Device Type.
  Organization, KB Number, Device, Days remain single-select
  (each is naturally a one-value pick).

### Documentation
- New "Where to find REJECTED patches" section in `CONTEXT.md` —
  points operators at the Current Patch State pie's grey slice
  (click-through), the Patch Detail Status filter, and the
  `compliance_all` Rejected column. Confirms REJECTED is audit-
  able even though it's excluded from compliance numbers.

### Notes / honest caveats
- `isMultiSelect` JSON shape is documented in Metabase but varies
  slightly by version. First time using it in this codebase. If
  a dropdown still acts single-select after rebuild, the shape
  needs adjustment — verify the dashboard parameter JSON via the
  Metabase API.

## [0.13.7] — 2026-06-04

### Changed
- **Patch Compliance formula clarified and centralized.** REJECTED
  and DELAYED patches are now **excluded** from both numerator and
  denominator on every compliance card. REJECTED is an explicit
  opt-out from policy; DELAYED is sitting in the org's configured
  30-day auto-approval window — both are conscious decisions, not
  coverage gaps.
- New single source of truth in `metabase_bootstrap.py`:
  `COMPLIANCE_MISSING_STATES = ("APPROVED", "MANUAL", "FAILED",
  "PENDING")` + `_COMPLIANCE_CTES` reusable SQL fragment. All 6
  compliance cards (`overall_compliance`, `org_compliance`,
  `compliance_worst`, `compliance_all`, `org_device_type`,
  `org_os_family`) now use the same formula via the same CTE
  block.
- `compliance_all` table gained a "Compliance-Scope Patches" column
  showing the denominator (installed + missing) alongside the
  existing "Total Patches" (every (device, patch) we've ever seen,
  including REJECTED/DELAYED). The difference between the two
  columns is the count of REJECTED + DELAYED rows — operator can
  audit at a glance.

### Documentation
- New "Patch Compliance formula" section in `CONTEXT.md` explains
  the formula, what counts as missing vs excluded, and where the
  implementation lives.

### Process
- **New `BLUEPRINT.md` per project.** Per the new Agent Work Rule
  #5 added to `Development/DEVELOPMENT.md`, every non-trivial task
  starts with a blueprint written to `BLUEPRINT.md` at the project
  root (overwritten per task). Lets interrupted sessions resume
  cold. This commit is the first one to follow the rule.

## [0.13.6] — 2026-06-04

### Added
- **Device Type (Server / Workstation) filter on Patch Command
  Center, Overall Patching Status, and Trends.** Org Overview, Patch
  Detail, and Device Patching Status already had it. Drilldown
  skipped (per-device, irrelevant).
  Three new per-dashboard parameter declarations
  (`PARAM_CMD_CLASS`, `PARAM_OVERALL_CLASS`, `PARAM_TRENDS_CLASS`)
  + matching template tag + mapping + SQL predicate fragment
  (`_CMD_DEVICE_TYPE_FILTER`, `_OVERALL_DEVICE_TYPE_FILTER`,
  `_TRENDS_DEVICE_TYPE_FILTER`). Each card on those dashboards now
  declares `template_tags` + `param_mappings` and its SQL is wired
  via the predicate fragment. Patch counts that didn't previously
  expose `device_id` had their CTE updated and a `JOIN
  ninja_core.devices d` added in the outer SELECT.

### Notes
- Three separate filter declarations rather than one shared global
  because Metabase's parameter IDs are dashboard-scoped — the same
  `param_mapping` shape wouldn't survive sharing.
- The cards on these dashboards now have `template_tags` even when
  they previously didn't — this is the trigger that makes the
  dashboard parameter visible / wired.

## [0.13.5] — 2026-06-04

### Removed
- **Patch Command Center orphan: `cmd_patch_activity_queue`
  (Stalled Devices table).** v0.11.4 dropped the Org Overview
  twin but missed Command Center. Same redundancy — the Stalled
  Devices scalar already exposes the count, and clicking it
  drills into Device Patching Status filtered to the stalled
  bucket.

### Changed
- `cmd_approval_queue` (Manual and Delayed Patches) now spans
  full width (size_x 24) — matches the Org Overview pattern
  established in v0.11.4.

## [0.13.4] — 2026-06-04

### Fixed
- **Org Overview's `Patch Compliance by Device Type` and `…by
  Operating System` charts were blank when no org was selected**,
  and showed 0% when one was. Two bugs at once:
    1. Same compliance bug class as v0.11.1 — the SQL counted
       `WHERE cs.status = 'INSTALLED'` against a CTE filtered to
       `fact_type='patch_state'`, which never contains INSTALLED.
       Rewrote to count from `install_outcome` over the universe
       of known (device, patch) pairs.
    2. Both charts had `GROUP BY o.name, <dimension>` — producing
       one row per (org, type) combination. The bar chart needs
       one row per type. Dropped `o.name` from SELECT/GROUP BY so
       the chart renders correctly with or without an org filter.
- Same `GROUP BY o.name` issue also fixed on Org Overview's
  Current Patch State pie (`org_status`).

### Added
- **`%` suffix** on the Patch Compliance scalar via a new
  `_SCALAR_SUFFIX_RULES` table and `_apply_scalar_suffixes`
  post-processor. Mirrors the pattern of the alert-color
  post-processor. Easy to extend with more suffixes later (e.g.
  " min", " days").

## [0.13.3] — 2026-06-04

### Added
- **Scalar background coloring** on attention-required tiles. Red
  if non-zero on: Failed Patches (all 3), Never-Patched Devices
  (all 4). Amber if non-zero on: Stalled Devices (all 4), Manual
  Approval (all 3), Needs Reboot (all 3).
- Implemented as a post-process step (`_apply_scalar_alerts`) over
  the existing card lists — declares rules in a single dict keyed
  by card key, then mutates each matching card's
  `viz_settings.column_settings.column_formatting`. Single source
  of truth for which scalars are alert-colored; easy to extend.

### Notes / honest caveats
- First time this codebase ships `column_formatting` JSON via the
  Metabase API. JSON shape from Metabase docs + community
  examples; varies slightly by version. If a scalar card shows no
  color post-deploy, that's the first thing to check.
- Patch Compliance ranges (green / amber / red by threshold) not
  yet added — wanted to start with the simpler "non-zero = alert"
  pattern. Can extend the rules table to support range coloring
  next.

## [0.13.2] — 2026-06-04

### Added
- **Activities backfill CLI** (`ingest/activities/backfill.py`) —
  operator-triggered one-shot that walks `/v2/activities` backward
  from the oldest record in DB via `olderThan=<id>` pagination.
  Uses the same allowlist as the forward ingest. Stops at the
  `--days` cutoff (default 90), `--max-pages` cap (default 500), or
  Ctrl-C. Idempotent — inserts are dedup'd on the activity-id PK.
  Does NOT touch the forward-ingest cursor in `ingest_state`.
  Run with: `docker exec ninja-ingest python -m ingest.activities.backfill --days 90`
- **Dashboard JSON export tool** (`ingest/metabase_export.py`) —
  fetches each provisioned dashboard via the Metabase API and
  writes pretty-printed JSON to `metabase/dashboards/<slug>.json`.
  For version-controlled snapshots of operator-side tweaks
  (column widths, custom filter values) that don't otherwise live
  in code. Reuses the bootstrap's auth + password-resolution
  helpers. Run with:
  `docker exec ninja-ingest python -m ingest.metabase_export --user X --password-file Y`.

## [0.13.1] — 2026-06-04

### Added
- **New Ninja — Trends dashboard.** Time-series rollups derived
  from the timestamps we already capture (no schema changes). Five
  cards:
    - Patch Installs per Day (bar, last N days)
    - Failed Install Attempts per Day (bar, red)
    - System Reboots per Day (bar)
    - Active Devices Seen per Day (line, from device_snapshots)
    - Currently-MANUAL Patches by Age (bar by week
      first_observed_at — shows how stale the admin queue is)
  Single "Timeline window (days)" filter, default 90.
- **Trends added to the nav bar** between Device Status and Patch
  Detail.

## [0.13.0] — 2026-06-04

### Added
- **Patches Installed Awaiting Reboot** table on Patch Command
  Center. Joins INSTALLED patches × `needs_reboot=true` × no
  `SYSTEM_REBOOTED` activity since last install. Surfaces the
  common patching-loop gap where install landed but reboot didn't.
  Click-throughs on Organization → Org Overview, Device → Drilldown.
- **Recent Patch Activity (Fleet)** table on Patch Command Center.
  Last 100 patch-lifecycle + reboot activities across the whole
  fleet, joined to device + org. Uses the same allowlist
  (`_DRILLDOWN_ACTIVITY_CODES`) as the per-device card on Drilldown.

### Changed
- `_DRILLDOWN_ACTIVITY_CODES` and `_DRILLDOWN_ACTIVITY_CODES_SQL`
  moved to the top of the file (near the color palettes) so they
  resolve before COMMAND_CARDS at module import time.

## [0.12.7] — 2026-06-04

### Added
- **Data Freshness scalar** on Overall Patching Status (top-right,
  next to Patch Compliance). Reads `MAX(started_at)` from
  `ninja_core.run_log WHERE status='ok'` and reports either "N min
  ago" or, if > 3 hours, "STALE — last ok run N h ago". Surfaces
  ingest failures explicitly instead of silently showing stale
  numbers.

### Notes / partial
- Patch Compliance scalar size shrunk from full-width (24) to
  size 18 to make room for Data Freshness (size 6) on the same row.
- This is item 10 of the backlog. The other queued items
  (awaiting-reboot panel, fleet-wide activity feed, trends
  dashboard, scalar coloring, backfill script, JSON export) are
  still pending.

## [0.12.6] — 2026-06-04

### Changed
- **Device Drilldown activity feed cleaned up.** The "Recent
  Activity" table was showing every activity the ingest collected
  for the device, including non-patch / non-reboot rows when the
  ingest's `INGEST_ACTIVITY_TYPES_INCLUDE` was broader than the
  dashboard's purpose. Added a SQL-side allowlist
  (`_DRILLDOWN_ACTIVITY_CODES`) so the card now only shows the
  patch-lifecycle codes plus `SYSTEM_REBOOTED`.
- Card renamed: "Recent Activity" → **"Recent Patch & Reboot
  Activity"** so the operator knows what to expect.
- `PATCH_MANAGEMENT_MESSAGE` is intentionally excluded from the
  card's allowlist (noisy generic info code). Operator can edit
  `_DRILLDOWN_ACTIVITY_CODES` to tweak.

### Notes
- This is a dashboard-side filter only. The ingest is unchanged —
  if `INGEST_ACTIVITY_TYPES_INCLUDE` is permissive, the rows still
  land in `ninja_activities.activities`; the Drilldown just doesn't
  show them. Other tools / future cards can still query the full
  set.

## [0.12.5] — 2026-06-04

### Added
- **Section header dividers between scalar groups.** Virtual text
  dashcards now mark the boundaries between groups on the three
  main dashboards:
    - Patch Command Center → **Devices** / **Patches**
    - Overall Patching Status → **Compliance** / **Devices** /
      **Patches**
    - Org Overview → **Compliance** / **Devices** / **Patches**
  Each header is a markdown `### Title` rendered via a Metabase
  virtual text card (single row, full width).

### Changed
- `_set_dashboard_layout` accepts an optional `section_headers`
  list and shifts cards at/below each header's original row down by
  `SECTION_HEADER_HEIGHT` to make room. Card specs keep their
  natural row numbers (0, 4, 8…); the layout helper computes the
  offset.
- `build_dashboards` now declares `section_headers` per dashboard
  alongside `cards` / `parameters`.

### Notes
- Drilldown, Patch Detail, and Device Patching Status didn't
  receive headers — they don't have the device/patch/compliance
  scalar grouping pattern.
- If Metabase's virtual text dashcard rejects this exact JSON
  shape, the dashboard PUT will 4xx — should fall back cleanly
  since pass 1a still creates the dashboards (just without the
  layout) and pass 2 click_behaviors don't touch dashcards.

## [0.12.4] — 2026-06-04

### Added
- **Pie / bar color coding (green / amber / red).** Two shared
  palettes baked into the bootstrap:
    - `PATCH_STATE_COLORS` — by patch_facts.status value. INSTALLED
      green, APPROVED/DELAYED blue, MANUAL amber, FAILED red,
      REJECTED grey.
    - `PATCH_ACTIVITY_COLORS` — by device patching state. Patching
      Devices green, Stalled Devices amber, Never-Patched Devices
      red.
  Applied to: Current Patch State pies on Overall Status, Patch
  Detail, Device Drilldown, and Org Overview; Patching Status pie
  + Operating-System stacked bar on Device Patching Status.

### Notes
- Section header markdown dividers between scalar groups still
  deferred — needs a layout-shift refactor to insert virtual
  cards between existing rows.
- Scalar background coloring also deferred — Metabase
  column_formatting JSON shape varies by version and would need
  live verification first.

## [0.12.3] — 2026-06-04

### Added
- **Needs Reboot** scalar on Overall Patching Status (Fleet) — was
  only on Command Center; now both dashboards expose it as the
  fifth tile in the Devices row.
- **Patching Devices** and **Needs Reboot** scalars on Org Overview
  — Org now has the full canonical Devices row: Active · Patching ·
  Stalled · Never-Patched · Needs Reboot.
- **Severity filter wiring** on the remaining 5 Org Overview patch
  scalars (Failed Patches, Approved Patches, Manual Approval,
  Delayed Patches, Current Patch State pie). Each CTE now selects
  `severity`, and `_ORG_FILTERS_PATCH_CS` / `_ORG_FILTERS_PATCH_LIR`
  applies the predicate. Every Org dashboard filter now narrows
  every applicable card.

### Changed
- Overall Patching Status and Org Overview row-4 layouts reflowed
  from 3–4 scalars at size 6/8 to **5 scalars at sizes 5+5+5+5+4**
  to match Command Center.

## [0.12.2] — 2026-06-04

### Changed
- **Device Drilldown's `Patch History` table split into two tables.**
  The old single table commingled `fact_type='patch_state'` rows
  (current state of pending patches) and `fact_type='install_outcome'`
  rows (install attempts). One column called "Current Patch State"
  meant different things on different rows. Now:
    - **Patch State History** (`device_patch_state_history`) — only
      `fact_type='patch_state'` rows. Columns: Device · KB · Patch ·
      Patch State · Severity · First Seen in This State · Last Seen.
    - **Install History** (`device_install_history`) — only
      `fact_type='install_outcome'` rows. Columns: Device · KB ·
      Patch · Install Outcome · Severity · Install Attempt Time ·
      Last Seen.
- **Org Overview cards now honor the dashboard filters.** Every Org
  card's SQL was updated to apply Organization + Device Type + OS
  Family filter predicates via the `_ORG_FILTERS_DEVICE` helper. The
  two patch-context tables (`org_failed_queue`, `org_action_queue`)
  additionally honor the Severity filter via `_ORG_FILTERS_PATCH_LIR`
  / `_ORG_FILTERS_PATCH_CS` helpers.

### Notes / deferred
- Severity filter only wired to the two patch-context tables.
  Adding it to other patch cards requires CTE rewrites to expose
  severity to the FROM/WHERE clauses; deferred.
- Section header markdown cards between scalar groups: still not
  added — visual row-grouping is in place, explicit headers are
  not.
- Color coding (green/amber/red): still deferred.
- Patching Devices scalar on Org Overview and Needs Reboot scalar
  on Overall Status / Org Overview: still not added.

## [0.12.1] — 2026-06-03

### Changed
- **Consistent card grouping across Command Center, Overall Patching
  Status, and Org Overview.** Each of the three dashboards now uses
  the same row structure for top-of-page scalars:
    - *Devices* row: Active · Patching · Stalled · Never-Patched
      (Command Center also includes Needs Reboot here — see notes).
    - *Patches* row: Approved · Manual · Delayed · Failed.
  Cards reordered in code to match this canonical order; charts and
  tables shifted to higher row numbers to make room.
- **Overall Patching Status now has a full-width Patch Compliance
  headline scalar** at row 0. Compliance is neither a device nor a
  patch metric — it's a top-level KPI and lives at the top of the
  page now.
- **Org Overview Patch Compliance scalar** moved from row 0 col 6 (a
  small tile next to Active Devices) to row 0 col 0 size 24
  (full-width headline) — same prominence as Overall Patching Status.

### Added
- **Org Overview dashboard filters:** Device Type, OS Family, and
  Severity dropdowns alongside the existing Organization filter.
  Filter helpers (`_ORG_FILTERS_DEVICE`, `_ORG_FILTERS_PATCH_CS`,
  etc.) defined for use across the Org cards.

### Notes / deferred
- **Per-card SQL wiring to the new Org filters is not yet
  applied** — the dropdowns are defined and visible but every Org
  card still queries the full org dataset. Wiring each card's SQL
  to use `[[AND ...]]` predicates is queued for v0.12.2.
- **Section header markdown cards** ("Devices" / "Patches" /
  "Compliance" subheadings between groups) are deferred — the
  visual grouping by row is in place, but explicit headers are
  not yet added.
- **Color coding** (green/amber/red) deferred to v0.12.2.

## [0.12.0] — 2026-06-03

### Changed
- **Dashboard renames** to disambiguate the two "status" views:
    - "Ninja — Overview" → **"Ninja — Overall Patching Status"**
      (fleet-wide rollup of compliance + state breakdowns)
    - "Ninja — Patching Status" → **"Ninja — Device Patching Status"**
      (per-device classification: Patching / Stalled / Never-Patched)
  Bootstrap renames each in place if the legacy name is found, so
  existing dashboard IDs (and Metabase favorites / shared links)
  survive.
- Nav bar labels condensed to **"Overall Status"** and **"Device
  Status"** to fit the strip.
- **Device Patching Status row 0** reordered so **Active Devices**
  is leftmost, consistent with every other dashboard. Order is now
  Active · Patching · Stalled · Never-Patched.

### Added
- **Patch Command Center is now the Metabase default homepage.**
  Bootstrap PUTs `custom-homepage=true` +
  `custom-homepage-dashboard=<command_center_id>` so operators
  land there instead of the generic Metabase home. Best-effort —
  on API rejection (older Metabase versions), the bootstrap logs a
  warning and continues; operator can set it manually via Admin →
  Settings → General → Custom Homepage.

## [0.11.4] — 2026-06-03

### Fixed
- **Full click-thru audit.** Applied the v0.10.2/v0.11.3 lesson
  (lowercase snake_case SQL aliases for click-source columns) to
  every remaining table that still used the capitalized quoted
  pattern: `cmd_failed_queue`, `cmd_approval_queue`,
  `cmd_patch_activity_queue`, `detail_all_devices`, `detail_all_kbs`,
  `detail_table`, `device_patch_history`, `pcov_by_org`,
  `pcov_all_devices`, `org_failed_queue`, `org_action_queue`. Every
  click-source column is now an unquoted snake_case alias with its
  `column_click_behavior` key matching exactly.

### Changed
- **Org Overview reflowed.** Removed the `Stalled Devices` table
  (`org_patch_activity`) that lived as a half-width card next to
  `Manual and Delayed Patches`. The stale/never-patched populations
  are already exposed by the org_stale / org_never scalars and the
  Devices Needing Reboot table — the orphan table was redundant.
- `Manual and Delayed Patches` table (`org_action_queue`) now spans
  full width (size_x 24).

## [0.11.3] — 2026-06-03

### Fixed
- **`Devices Needing Reboot` click misalignment** (Fleet + Org).
  After v0.11.2 enabled per-column click_behavior at the dashcard
  level, the device + device_type columns drilled correctly but
  organization clicks did nothing and last_contact wrongly
  navigated to Org Overview. Two corrections:
    1. Removed the `target: "self", preset: {}` inert placeholders
       on info columns (last_contact, reported_at, "Last Contact").
       They were the v0.7.4 "suppress the default drill popup"
       experiment and were misaligning real click_behaviors to the
       wrong columns. Trade-off: info columns now show the default
       Metabase drill popup; the meaningful drills work cleanly.
    2. Gave every column an explicit lowercase `AS` alias and
       converted `org_reboot_devices` (Org Overview) from
       capitalized-quoted aliases to the same lowercase pattern
       Fleet's `needs_reboot` now uses.

## [0.11.2] — 2026-06-03

### Fixed
- **Per-column table click-thrus still showed Metabase's default
  "filter by this value" popup** after v0.11.1, even though
  whole-card click_behavior (e.g., bar charts) was working fine on
  the same dashboards. Root cause: Metabase silently ignores
  per-column `click_behavior` set in the **card**'s
  visualization_settings; it only honors it when set on the
  **dashcard**'s visualization_settings. The bootstrap was writing
  both whole-card and per-column behaviors to the card; the latter
  had no effect. Fix: per-column click behaviors are now written
  during dashboard layout (pass 1b) into each dashcard's own
  `visualization_settings.column_settings`. Whole-card
  `click_behavior` stays at the card level (it works there). Affects
  Command Center "Clients Needing Attention", Fleet Overview
  "Client Patch Compliance" / "Devices Needing Reboot", Org
  Overview tables, Patch Detail / Drilldown / Patching Status tables.

## [0.11.1] — 2026-06-03

### Fixed
- **Patch Compliance always 0.** Fleet Overview's `Clients with
  Lowest Patch Compliance` chart, `Client Patch Compliance` table,
  and Org Overview's `Patch Compliance` scalar all reported 0 % for
  every client. The compliance numerator counted
  `WHERE status='INSTALLED'` against a CTE filtered to
  `fact_type='patch_state'`, but per the v0.9.0 split, INSTALLED
  rows live in `fact_type='install_outcome'`. The patch_state side
  never contained any installs, so the numerator was always 0.
  Compliance now computes installed = distinct (device, patch) with
  any install_outcome=INSTALLED row over the universe of all
  (device, patch) pairs we know about.
- **Fleet Overview table click-thrus didn't navigate.** Per the
  v0.10.2 lesson, Metabase per-column click_behavior is more
  reliable referencing stable lowercase snake_case SQL aliases than
  quoted display strings (`"Organization"`, `"Device"`, etc.).
  `Client Patch Compliance` and `Devices Needing Reboot` both used
  the quoted-display pattern; they now use `organization`,
  `device`, `device_type` aliases with click keys to match.

### Added
- **Patching Devices** scalar on Patch Command Center — completes
  the device-state triple (Patching / Stalled / Never-Patched) that
  was already on Fleet Overview but missing here. Row 4 reflowed to
  5 scalars at widths 5+5+5+5+4.

## [0.11.0] — 2026-06-03

### Added
- **Cross-dashboard nav bar.** Every dashboard now opens with a
  one-row markdown panel linking to the other dashboards in the set
  (Command Center · Fleet Overview · Org Overview · Patching Status ·
  Patch Detail · Device Drilldown). The current dashboard is bolded
  without a link. Implemented via Metabase virtual text dashcards
  (`card_id: null` + `visualization_settings.virtual_card`).
- Fleet Overview now splits the lumped **Manual / Delayed** scalar
  into **Manual Approval** and **Delayed Patches** (consistent with
  Command Center and Org Overview). Row 0 reflowed to 5 scalars
  (Active Devices · Approved Patches · Manual Approval · Delayed
  Patches · Failed Patches).

### Changed
- Terminology pass for consistency across all 6 dashboards:
  - **Patching Status** (overloaded as both a dashboard name and a
    card title for the patch_facts.status pie) → the pie card title
    is now **Current Patch State** everywhere. The PCOV dashboard
    keeps "Patching Status" as the dashboard concept.
  - **Patch Activity** (PCOV dashboard column + filter + card
    titles) → **Patching Status**. Card titles are now "Patching
    Status by Device Type / OS / Organization".
  - Device-state triple uses unambiguous device-focused labels:
    **Patching Devices / Stalled Devices / Never-Patched Devices**
    (previously "Recent Patch Activity / Stale Patching / Never
    Patched" — which read as patch states, not device states).
  - **Delayed Install** → **Delayed Patches** (parallels Approved /
    Failed / Manual).
  - **Approved Windows Devices** (Patching Status total) → **Active
    Devices** (consistent with Fleet and Org).
  - SQL aliases, viz dimension references, dropdown values, and
    click-behavior column keys all renamed in lockstep so dashboards
    keep working.
- `_set_dashboard_layout` now accepts an optional `nav_markdown` and
  shifts every card down by `NAV_HEIGHT` rows when present. Card
  specs keep their natural row numbers (0, 4, 8…) — the helper
  inserts the offset.
- `run_bootstrap` restructured into three passes: cards+dashboards
  first, then layouts (with nav bar) once all dashboard IDs are
  known, then click behaviors.

## [0.10.2] — 2026-06-03

### Fixed
- Fixed the **Clients Needing Attention** organization click on
  **Ninja — Patch Command Center** by restoring a stable lowercase
  `organization` SQL alias for Metabase's table-column click behavior.
- Clarified mixed-unit table columns so patch counts say `Patches`
  and device counts say `Devices`.

## [0.10.1] — 2026-06-03

### Fixed
- Changed the default stale-patching threshold from 7 days to 35 days
  to match real MSP patch cadence, where devices may patch weekly or
  monthly.
- Centralized the non-filter dashboard stale threshold as
  `DEFAULT_STALE_PATCH_DAYS` so Command Center, Overview, and Org
  Overview do not drift from each other.
- Kept **Ninja — Patching Status** configurable via the dashboard
  `Stale threshold (days)` filter, now defaulting to 35.

## [0.10.0] — 2026-06-03

### Added
- New **Ninja — Patch Command Center** dashboard as the operator
  landing page. It surfaces fleet-wide action queues for clients
  needing attention, failed patches, manual/delayed patches, stale
  patching, never-patched devices, and reboot work.
- Operating-system dashboard filters now use stable OS families:
  `Windows 11`, `Windows 10`, `Windows Server`, `Other Windows`, and
  `Unknown`.

### Changed
- Rebuilt **Ninja — Org Overview** as an actionable client patching
  view instead of a mostly decorative summary page. It now has
  org-scoped KPIs plus queues for failed patches, manual/delayed
  patches, stale/never-patched devices, and reboot attention.
- Dashboard labels and visible table columns now use operator-facing
  terminology: `Active Devices`, `Approved Patches`, `Manual
  Approval`, `Delayed Install`, `Failed Patches`, `Recent Patch
  Activity`, `Stale Patching`, `Never Patched`, `Device Type`,
  `Operating System`, `Patching Status`, and `Install Results`.
- Device Type filters now use readable values (`Windows Workstation`,
  `Windows Server`) instead of raw Ninja node-class codes.
- Query-string drill links now URL-encode preset filter values so
  dashboard links work with labels containing spaces.

## [0.9.0] — 2026-06-03

### Added
- `ninja_patches.patch_facts.fact_type` now explicitly marks rows as
  `patch_state` (`/queries/os-patches`) or `install_outcome`
  (`/queries/os-patch-installs`). Migration
  `006_patch_fact_type.sql` backfills existing rows by status.

### Changed
- Patching Status stale/active classification now uses the latest
  available install/attempt timestamp (`MAX(installed_at)`) from
  `install_outcome` rows. The `Stale threshold (days)` dashboard
  filter continues to control the active/stale split.
- Dashboard SQL that needs install outcomes now filters by
  `fact_type = 'install_outcome'` instead of inferring source from
  status values.

## [0.8.1] — 2026-06-03

### Fixed
- Split dashboard patch semantics into **current patch state** and
  **latest install outcome**. A patch can currently be `APPROVED`
  while its most recent install attempt is `FAILED`; the old
  current-state-only queries hid those failed installs.
- Fleet and Org **Failed Installs** cards now count the latest
  `FAILED` install outcome per `(device_id, patch_uid)`.
- Patch Detail now has an **Install Outcome** filter separate from
  the current-state **Status** filter, and the detail table shows both
  `current_status` and `last_install_outcome`.
- Org Top Problem Patches now prioritizes latest failed install
  outcomes while still showing current queued states.

## [0.8.0] — 2026-06-03

### Added
- New **Ninja — Org Overview** dashboard. Fleet org clicks now drill
  into this org-scoped overview instead of jumping straight to the
  flat Patch Detail list.
- Patch Detail now has a real **Device** dropdown filter populated
  from active Windows devices.

### Changed
- Renamed **Ninja — Patch Coverage** to **Ninja — Patching Status**.
  Bootstrap renames the old dashboard in place when found.
- Device Drilldown now uses an exact Device dropdown instead of a
  free-text substring filter.
- Dashboard scope is now Windows patching only:
  `WINDOWS_WORKSTATION` and `WINDOWS_SERVER`.

### Database
- Migration `005_active_windows_devices_view.sql` replaces
  `ninja_core.v_active_devices` on already-deployed stacks so the
  Windows-only scope applies even if migration `004` already ran.

## [0.7.4] — 2026-06-03

### Changed
- **Consistent table click behavior.** Previously, table cells with a
  configured drill (colored link) navigated as expected, but cells in
  unconfigured columns showed Metabase's default "filter by this
  value" drill-through prompt — which is meaningless on tables that
  have no logical filter destination. Each table now declares every
  column's behavior explicitly: meaningful columns navigate; purely
  informational columns (timestamps, durations, status text on
  diagnostic tables) get a self-link with empty preset to suppress
  the prompt.
    - `needs_reboot`: `last_contact`, `reported_at` → inert.
    - `ingest_health`: all 7 columns → inert (it's diagnostic; no
      drill destination makes sense).
- `_build_click_behavior_json` now accepts `current_dash_id` and
  resolves `target: "self"` in the preset path to a URL pointing at
  the current dashboard (empty preset = no-op self-link).

## [0.7.3] — 2026-06-03

### Added
- **Number cards drill into target dashboards on click.** Previously
  clicking a scalar tried to "filter for this value" (meaningless on
  a one-cell display). Now each scalar pre-sets a filter on the
  target dashboard via a URL link:
    Overview "Patches Ready" → Detail filtered to APPROVED
    Overview "Failed" → Detail filtered to FAILED
    Overview "Manual / Delayed" → Detail filtered to MANUAL
    Overview "Active Devices" → Detail (no filter — see all)
    Overview "Patching Active (7d)" → Patch Coverage filtered to active_patching
    Overview "Patching Stale" → Patch Coverage filtered to stale_patch_data
    Overview "No Patch Data" → Patch Coverage filtered to no_patch_data
    Patch Coverage scalars → same dashboard with `pcov_status` pre-set

### Fixed
- Five stray `ORDER BY n DESC` references that should have been
  `ORDER BY patches DESC` — leftover from the earlier `AS n` →
  `AS patches` rename. Caused "column 'n' does not exist" on Patch
  State Breakdown and the four Detail charts.
- `COUNT(*) AS needs_attention` had been corrupted to
  `COUNT(*) AS patcheseeds_attention` by the same blunt replace —
  fixed back. Operator never saw this fail because the card with
  the corrupted column returned NULL (which Metabase rendered as
  "no value").

## [0.7.2] — 2026-06-03

### Fixed
- **Metabase bootstrap was crashing silently** with
  `NameError: name 'DASH_DETAIL' is not defined` at module import.
  The four dashboard-name constants (DASH_OVERVIEW / DASH_DETAIL /
  DASH_DRILLDOWN / DASH_PCOV) were defined ~300 lines below the
  card specs that referenced them — Python tries to resolve those
  names at module-load time, fails. Constants moved to the top of
  the file, before any card definitions.
- **Impact:** since v0.5.0 the auto-bootstrap has been throwing
  this NameError on every container start (logged but not raised
  by `bootstrap_metabase`'s try/except). All dashboard changes
  shipped between v0.5.0 and v0.7.2 — patch coverage tunings, OS
  bar fix, active-devices view, click behaviors, workstation
  default — haven't actually been applied to your Metabase.
  This commit unblocks all of those at once.

## [0.7.1] — 2026-06-03

### Fixed
- Activities ingest now filters server-side by `statusCode=<code>`
  (one call per allowlist entry) instead of `type=<source>` with
  client-side filtering. This:
    - Catches SYSTEM_REBOOTED reliably regardless of which Ninja
      `type` bucket it lives in. (`type=SYSTEM` we'd been using
      returns Ninja platform audit events — admin logins, node
      access grants — NOT device reboots.)
    - Reduces API surface: 10 small targeted calls instead of pulling
      whole MONITOR / PATCH_MANAGEMENT / SYSTEM buckets and dropping
      most records.
    - No more risk of silently missing relevant events because they
      happen to be filed under a different bucket.
- Empty `INGEST_ACTIVITY_TYPES_INCLUDE` falls back to old
  `type=<source>` behavior (backward compat) with a WARN log
  encouraging operator to set the allowlist.

## [0.7.0] — 2026-06-03

### Performance

Patch ingest stops re-walking the entire 376k install history every
hour. The two patch endpoints now use different strategies:

  - `/queries/os-patch-installs` (events: INSTALLED, FAILED) →
    INCREMENTAL via `?installedAfter=<unix_seconds>`. High-water
    mark = MAX(installed_at) currently in patch_facts. First run
    pulls everything; subsequent runs pull only patches installed
    since the last seen install.
  - `/queries/os-patches` (state: PENDING, APPROVED, REJECTED,
    DELAYED, MANUAL) → FULL PULL each run. State transitions don't
    always carry a usable timestamp, and the set is small (~50k).

Impact: a normal hourly tick that previously HTTP'd 376k records
now HTTP's only the handful installed in the last hour, plus the
~50k state records. Estimate: minutes → seconds per cycle.

SCD-2 hash dedup means re-fetching boundary records (anything
installed at the same second as our high-water mark) is harmless.

## [0.6.1] — 2026-06-03

### Removed
- `triggered_by_user_id` column from the Device Drilldown's "Recent
  Activities" card. Ninja's `userId` is internal audit (which API
  client/service triggered the event), not the device's logged-in
  user or an MSP technician — no business value. Schema keeps the
  column to avoid a destructive migration but it's no longer
  surfaced anywhere. Documented as permanently-parked in TODO.md.

## [0.6.0] — 2026-06-03

### Added
- **Activities ingest is now working** end-to-end against the live
  Ninja instance. Findings from `probe_activities.py`:
    - Server-side filter param is `type=<source>` (NOT `activityType`
      — that one is silently ignored).
    - Pagination back: `olderThan=<id>` walks to older records.
    - Pagination forward: `after`/`newer`/`newerThan`/`from` all work
      equivalently (we use the high-water mark approach: walk back
      with `olderThan` from latest, stop when we cross our cursor).
  Per source (PATCH_MANAGEMENT, SYSTEM, etc.), iterate older pages
  until cross last_id, filter by statusCode allowlist, insert with
  ON CONFLICT DO NOTHING (id is PK).
- Activity records are joined to `ninja_core.devices` via
  `deviceId`. If Ninja reports activity for a device we don't ingest
  (PENDING / DECOMMISSIONED), `device_id` is NULL'd (activity still
  recorded, just without device link).
- **Device Drilldown** gains a "Recent Activities" table showing
  the last 200 activities for the searched device — event code,
  human label, message, the **userId who triggered it**, and the
  activity category. That's the "by whom" surface for events that
  carry it (login, software install, etc.).

### Field mapping (Ninja API → our schema)
  `id`           → `id`
  `activityTime` → `activity_time`
  `deviceId`     → `device_id` (NULL if device not in our table)
  `userId`       → `user_id` (the user who TRIGGERED the activity)
  `activityType` → `source_name` (broad bucket: MONITOR, PATCH_MANAGEMENT...)
  `type`         → `source_type` (friendly name)
  `statusCode`   → `activity_type` (specific event code)
  `status`       → `subject` (human label)
  `message`      → `message`

### Process
- VERSION 0.6.0. Activities is a new functional capability (not just
  a bugfix); first time we're surfacing Ninja's event log.

## [0.5.1] — 2026-06-03

### Fixed
- Patch Coverage by OS card: `ORDER BY (active + stale + no_data)`
  referenced column aliases inside arithmetic — Postgres doesn't
  allow that at the same SELECT level. Switched to `ORDER BY
  COUNT(*) DESC` (same result, valid SQL).

## [0.5.0] — 2026-06-03

### Added — interactive dashboards

Click-behavior wired across charts and tables, enabled by a new
two-pass provisioning model: pass 1 creates cards / dashboards /
layouts, pass 2 applies `click_behavior` (needs dashboard IDs from
pass 1 for cross-dashboard drill-through).

  - **Charts**: click a slice / bar to filter. Pies, severity bars,
    top-N bars all wired. Cross-filter (same dashboard) or drill-link
    (other dashboard) depending on which makes sense.
  - **Table columns**: per-column click behavior in all major tables.
    Click a Device cell → opens Device Drilldown for that device.
    Click an Org / Status / KB / Node Class cell → cross-filters the
    current dashboard.

Specific wires:

  - Overview pie → opens Detail filtered by status
  - Overview compliance bar → opens Detail filtered by org
  - Overview compliance table (org column) → opens Detail by org
  - Overview reboot table (device col) → Drilldown; (org col) → Detail
  - Detail pies/bars → self-filter the Detail dashboard
  - Detail tables (device col) → Drilldown
  - Detail top-devices bar → Drilldown for the clicked device
  - Drilldown patch history (kb col) → Detail filtered by KB
  - Patch Coverage pies/bars → self-filter the Coverage dashboard
  - Patch Coverage device col → Drilldown

### Changed

- Node Class filter defaults to `WINDOWS_WORKSTATION` on Detail and
  Patch Coverage. MSP "workstations first" workflow now is the
  default view; pick `WINDOWS_SERVER` / others from the dropdown.

### Process

- VERSION 0.5.0. Two-pass provisioning is a meaningful architecture
  change to the bootstrap script (worth tracking).

## [0.4.0] — 2026-06-03

### Added
- New SQL view `ninja_core.v_active_devices` defined as: approved
  AND last contact within 30 days. The view exposes the latest
  device_snapshots fields inline (`last_contact`, `last_boot`,
  `needs_reboot`, `maintenance_*`, etc.) so downstream queries
  don't need to re-join the snapshots table.
- Migration `004_active_devices_view.sql` creates the view on next
  container start (run by ingest.migrations).
- Patch Coverage all-devices table gains `last_contact` and
  `days_since_contact` columns. Combined with `patch_status`,
  operators can spot devices that are both stale-patching AND
  hardware-unreachable (decommission candidates) vs stale-patching
  but contactable (agent / config problem).

### Changed (behavioral)
- **Overview and Detail dashboards now filter to "active devices"**
  (the new view's definition). Counts, compliance %, top-N, all-orgs,
  and the patch detail table all narrow to the active fleet.
- Drilldown deliberately stays on raw `ninja_core.devices` so you
  can still investigate inactive / decommissioned devices.
- Patch Coverage deliberately stays on raw devices so it surfaces
  the very devices the active-view excludes.

### Process
- VERSION bumped to 0.4.0 — semantic change to default scope of
  multiple dashboards is a MINOR bump even though backward-
  compatible at the SQL level.

## [0.3.1] — 2026-06-03

### Added
- Overview gains a "Patch Coverage" summary row: Active (last 7d) /
  Stale (>7d) / No Data Ever — three numbers above the existing
  pie/compliance row. Subsequent rows shifted down accordingly.
- Patch Coverage dashboard:
  - **Stale threshold (days)** dashboard parameter — operator picks
    the cutoff at the top, default 7. CTE uses it dynamically.
  - **Node Class pie** — breakdown of devices in the current filter
    set by node_class.
  - **OS stacked bar** (top 20 OSes) — for each OS, active vs stale
    vs no_data counts. Best way to see if a particular Windows /
    Linux / Mac flavor has a coverage problem.
- Detail dashboard: **Timeline window (days)** parameter, default 90.
  Only the install-timeline card maps it; others ignore.
- Drilldown dashboard: **Timeline window (days)** parameter, default
  180. Same pattern.

### Process
- VERSION bumped to 0.3.1 (additive features + UX polish, no breaking
  changes).

## [0.3.0] — 2026-06-03

Dashboards stage. Stack now ships three Metabase dashboards
auto-provisioned on container startup; bootstrap script is
operator-set-and-forget.

### Added
- `ingest/metabase_bootstrap.py` — idempotent CLI + library that
  provisions Metabase collections, cards, dashboards, layouts via
  REST API. Supports template-tag-based dashboard filters with
  dropdown sources populated from live Postgres data.
- Auto-bootstrap on ingest container startup, gated on
  `MB_BOOTSTRAP_USER` / `MB_BOOTSTRAP_PASS` env vars. Waits up to
  5 min for Metabase to come up, checks first-run wizard is
  complete, tolerates all failures (logged, not raised).
- `POST /bootstrap-metabase` HTTP endpoint for manual re-provision
  without container restart.
- Dashboard: **Ninja — Overview** — 9 cards: active devices,
  patches ready / manual+delayed / failed (numbers); patch state
  donut; worst-15 + all-orgs compliance; reboot table; ingest
  health.
- Dashboard: **Ninja — Patch Detail (Filterable)** — 8 cards behind
  6 dashboard filters (Org dropdown, Status, Node Class, Severity,
  OS Name, KB Number). Status donut, severity bar, top-15 + all
  devices, top-20 + all KBs, install timeline, full patch table.
- Dashboard: **Ninja — Device Drilldown** — per-device deep dive
  via free-text name search. Device info, patch state pie, 180-day
  install timeline, full patch history table (every SCD-2 row).
- Dashboard: **Ninja — Patch Coverage** — operational gap analysis.
  Classifies each approved device as active_patching /
  stale_patch_data / no_patch_data based on the most recent
  observation in patch_facts. Filters by Org / Node Class / OS /
  Patch Status. Useful for finding devices the patch agent is no
  longer reaching.
- `ingest/probe.py` + `ingest/probe_fields.py` — diagnostic CLIs
  for walking unknown Ninja endpoints and surveying custom-field
  shape before writing ingest code.

### Fixed
- `paginate_cursor` was infinite-looping on Ninja's `/queries/*`
  endpoints because cursor.name stays constant across pages.
  Termination now driven by `cursor.offset + len(results) >=
  cursor.count`.
- All pie charts show every slice (`pie.slice_threshold: 0`); the
  default 2.5% threshold was hiding small statuses as "Other".
- COUNT columns renamed from `n` to `patches` so tooltips read
  "patches: 47" instead of "n: 47".

### Process
- Going forward, VERSION bumps on each feature/fix commit; tags
  cut at milestones. CHANGELOG.md updated per commit.

## [0.2.0] — 2026-06-03

End-to-end ingest pipeline running against a live Ninja instance.
Stack is deployed on `am-ch-01` via Portainer git auto-update.

### Added
- Full ingest of organizations / locations / policies / devices /
  device_snapshots / custom_field_values / patch_facts / activities
  from `amrose.rmmservice.com`.
- `ingest/runlog.py` — reusable context manager that opens and
  closes a `ninja_core.run_log` row per module.
- `ingest/main.py` — APScheduler + threading HTTP server (`/healthz`,
  `/run`) wired through `_safe()` so a module crash doesn't kill the
  rest of the cycle.
- `ingest/util.py` — `ninja_epoch_to_dt`, `content_hash`.
- `ingest/probe.py` + `ingest/probe_fields.py` — diagnostic CLIs for
  walking endpoints and discovering custom field schemas without
  writing to the DB.
- `ingest/db.insert_ignore` — bulk INSERT ... ON CONFLICT DO NOTHING
  for immutable-event tables (`ninja_activities.activities`).
- `db.upsert(..., update_cols=...)` — column-scoped UPDATE for SCD-2
  tables that must preserve `first_observed_at`.
- Custom fields allowlist + value-size cap
  (`INGEST_CUSTOM_FIELDS_INCLUDE`, `INGEST_CUSTOM_FIELDS_MAX_TEXT`)
  so we don't ingest 20k-char HTML reboot reports into typed cells.
- Patches: batched upserts (5000 rows at a time) for memory bounded
  ingest of 376k+ patch records.

### Fixed
- `migrations.py` was importing `pool` directly from `ingest.db`,
  capturing the pre-init sentinel; switched to module reference.
- `paginate_cursor` was infinite-looping because Ninja keeps the
  cursor name constant across pages on `/queries/*` endpoints.
  Termination is now driven by `cursor.offset + len(results) >=
  cursor.count`, with stalled-offset detection as a guard.
- Postgres healthcheck was generating `FATAL role "root"` spam every
  10s — switched to socket-based `pg_isready -h /var/run/postgresql`
  so it bypasses `pg_hba` host rules.
- Init script renamed from bash to sh — `postgres:16-alpine` doesn't
  ship bash.
- `postgres.Dockerfile` bakes the init script into a custom image
  because Portainer Repository-mode doesn't extract repo files for
  runtime bind-mounts.
- `postgres-data` and `metabase-data` moved from host bind-mounts to
  named docker volumes — eliminates chown/wipe foot-guns.
- Compose env handling settled on bind-mount + entrypoint wrapper
  (`set -a; . /etc/secrets.env; set +a; exec ...`) since neither
  `${VAR}` substitution nor `env_file:` work in Portainer
  Repository-mode.

### Known limitations
- `custom_field_definitions` table is unpopulated; the live API has
  118 defined fields but only the 19 with `apiPermission != NONE`
  return values via `/queries/custom-fields`. Switching to a
  two-endpoint (`/v2/custom-fields` definitions + `/queries/
  scoped-custom-fields-detailed` values) parked for v0.3.
- Activities first run sets the cursor but doesn't backfill — only
  events newer than the cursor flow in. Backfill script is TODO.
- `needs_reboot_reasons` is captured as NULL on `device_snapshots`;
  need to confirm where Ninja exposes Windows reboot reasons.

## [0.1.0] — 2026-06-02

Initial scaffold. No working ingest yet — package layout, Docker
stack definition, database schemas, and supporting docs only.

### Added
- `REQUIREMENTS.md` — full design doc: architecture, decisions, schema,
  scope, expansion path.
- `CONTEXT.md` — project overview for new contributors / future sessions.
- `docker-compose.yml` — three-service stack (postgres, metabase,
  ingest).
- `Dockerfile` — Python 3.12-slim, non-root, healthcheck.
- `requirements.txt` — pinned ingest deps (httpx, psycopg, apscheduler,
  pydantic-settings, python-dotenv).
- `.env.example` — required environment variables.
- `ingest/` Python package skeleton: `config`, `ninja_client`, `db`,
  `migrations`, `main`, `core/`, `patches/`. No logic yet.
- `sql/init/00_create_databases.sh` — creates `ninja` and `metabase`
  databases + the `metabase` app user on first Postgres boot.
- `sql/migrations/001_init_core.sql` — `ninja_core` schema (orgs,
  locations, policies, devices, device_snapshots, custom fields,
  run_log, schema_migrations). SCD-2 baked into custom_field_values.
- `sql/migrations/002_patches.sql` — `ninja_patches.patch_facts`
  with SCD-2 / content-hash dedup.
- `sql/migrations/003_activities.sql` — `ninja_core.ingest_state` +
  `ninja_activities.activities`, filtered to patch lifecycle events
  + SYSTEM_REBOOTED.
- `ingest/activities/` package skeleton.
- `ingest/ninja_client.py` — implemented: OAuth2 client-credentials
  auth with token refresh, retry/backoff on 5xx/429, both pagination
  styles (`paginate_after`, `paginate_cursor`).
- `ingest/db.py` — implemented: psycopg-pool `ConnectionPool`,
  `transaction()` context manager, generic `upsert()` helper.
- `ingest/migrations.py` — implemented: discover `sql/migrations/*.sql`,
  apply pending in transaction-per-file, idempotent bootstrap.
- `ingest/smoke.py` — `python -m ingest.smoke` end-to-end sanity check
  (env → Postgres → migrations → Ninja API).
- `psycopg-pool==3.2.3` added to `requirements.txt`.
- `docker-compose.yml`: every service now uses
  `env_file: /amr-ch-01_data/ninja-dashboard/.env` instead of
  `${VAR}` substitution. Host `.env` is the single source of truth;
  no Portainer-side env panel needed. Pg healthcheck rewritten to
  use `$$VAR` shell-time substitution.
- **Compose env handling rewritten** (the saga's resolution): env
  vars come from the bind-mounted host `.env` read by each container
  at startup. Postgres + Metabase use entrypoint wrappers that source
  `/etc/secrets.env`; ingest uses python-dotenv on `/app/.env`.
  Sidesteps every Portainer-Repository-mode limitation (no
  `${VAR}`, no `env_file:` with abs paths, no repo-relative bind
  mounts at runtime).
- **Postgres init script baked into custom image** via
  `postgres.Dockerfile` instead of bind-mounted from `./sql/init`.
  The bind-mount path was always empty in Portainer Repository mode
  because Portainer doesn't extract repo files to disk for runtime
  use — only for build contexts.
- **Renamed `Dockerfile` → `ingest.Dockerfile`**; postgres now has
  its own `postgres.Dockerfile`. Both built by Portainer on push.
- **Switched `postgres-data` and `metabase-data` to auto-managed
  named volumes** instead of host bind-mounts under
  `/amr-ch-01_data/ninja-dashboard/`. Eliminates the chown/wipe
  foot-guns; `docker volume rm` is the unambiguous reset.
- Postgres healthcheck simplified to bare `pg_isready` (no env
  needed; docker exec doesn't inherit the entrypoint wrapper's env).
- `PORTS.md` — host port map + what this stack publishes
  (3001 Metabase on LAN; 8090 ingest on loopback; Postgres internal).
- `TODO.md`, `SESSIONS.md` per `Development/DEVELOPMENT.md` conventions.
- `.gitignore`, `.dockerignore`.
