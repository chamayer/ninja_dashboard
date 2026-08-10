# Active root implementation plan

## CURRENT TASK — ADR-0015 step 3: software findings onto software subjects

**Status:** step 0 (authorization) implemented locally, not committed or
deployed. Next action: step 1, the `catalog` bigint -> uuid migration.

Goal: "know about software installed on devices and be able to authorize /
report on them with findings." A finding about software is stored once on the
software; devices inherit it through the installation link.

### Measured (production, 2026-08-10) — do not re-derive

| type | open rows | by title | by (client, title) |
| --- | --- | --- | --- |
| whitelist_suggestion | 131,073 | 1,631 | 19,301 |
| vulnerable_software | 1,403 | 17 | 93 |
| eol_runtime | 630 | 106 | 214 |
| unauthorized_remote_access | 522 | 5 | 111 |
| suspicious_name | 383 | 5 | 62 |
| known_malicious_hint | 128 | 11 | 36 |
| unauthorized_av | 45 | 2 | 11 |

Intrinsic-to-software total: **134,484 rows -> ~1,777** (the `by title`
column). All seven assert a property of the *title*, not of a client:
a CVE, an EOL date, a suspect name, or an undecided authorization. The client
is never part of the claim — it only determines who is exposed, which is
derived by the join.

The `by (client, title)` column (19,828) answers the wrong question and is
retained only so nobody re-measures it. Storing per client would mean a single
global approval had to sweep 19,301 rows closed instead of resolving one.

`rare_recent` (2,658) and `install_path_suspicious` (398) stay on
`subject_type='device'` — recency and install path are per-device facts.

* **0** multi-version-per-device-title rows in active history. Limit 2 in the
  `074` docstring is theoretical — correct the docstring, do not change the PK.
* **0** of 137,540 software findings carry a version. Subject binds to
  `catalog.products`, not `software_versions`.
* `_resolve_decision` already implements device > client > global for title
  and publisher scope (`software_findings.py:137`).

### ADR-0015 is correct — do not amend it

Its predicted "137,534 -> 1,782" matches the measured ~1,777. An earlier claim
in this session that the ADR was "client-blind" was wrong: it modelled the
subject as the title, which is right, because none of the seven types asserts
anything about a client.

### Design

* Findings collapse to `(title)` — emitter change is dropping both `client_id`
  and `device_id` from `_condition_key`, and emitting with `client_id` NULL
  (`Finding.client` is already nullable).
* The three authorization tiers all resolve through one mechanism:
  * **global** approve -> the finding resolves, one row;
  * **client** approve -> finding stays open, that client's devices drop out
    of the exposure view;
  * **device** approve -> finding stays open, that device drops out.
  Client and device are filters on derived exposure, never stored rows.
* Device exposure is **derived, not stored**: `findings -> catalog.products ->
  software_versions -> software_installations_current.software_version_id ->
  device`, minus device-tier approvals. Patching a title fleet-wide then
  resolves one finding instead of 1,378.

### Authorization — step 0, done; smaller than it was described

Measured 2026-08-10, `operations.software_decisions`: global 427 (all CSV seed
import), client 0, device 0.

**Correction to the earlier reading of those zeros.** They were taken as proof
that no tier had a working operator path. Re-derived from the code
2026-08-10: all three tiers have a wired surface and a working handler, and
`software_decision_create` (`views.py:7514`) already accepts
`scope = global | client | device` and resolves `client_slug` / `device_id`
correctly. Zero rows means unused, not unreachable. Only one handler was
genuinely dead:

* **global** — the dead code was in `software_decision_bulk`, *not* the whole
  global path. Two `return redirect(...)` at function-body indentation made the
  `update_or_create` loop unreachable, so bulk apply silently no-opped. Fixed:
  both returns moved inside their validation `if`, and the two
  `_refresh_software_risk_matview()` calls dropped from those error paths —
  they refreshed a matview after writing nothing. Per-row global buttons on
  `software_decisions.html`, `software_products.html`, `software_publishers.html`,
  `software_detail.html` and `software_publisher_detail.html` always worked;
  they post to `software_decision_create`.
* **client** — `org_software_decide` (`views.py:6323`) works and is wired from
  `org_software.html:169`. Real defect: its `update_or_create` lookup omitted
  `device`, so a client decision would match and overwrite a device-scoped row
  for the same client and title. Fixed by adding `device=None` to the lookup.
* **device** — a surface does exist: the per-install row action in
  `software_detail.html:180` posts `scope=device` with `device_id`. Nothing to
  build.

Both follow-on defects are also fixed: `org_software_decide` no longer follows
an unvalidated `next` / `HTTP_REFERER` (open redirect — `HTTP_REFERER` is
attacker-settable), and `software_decision_bulk` now rejects a non-`global`
`scope` with an operator-visible message instead of silently writing a global
decision. Both bulk forms post `scope=global` today, so that one was latent,
not live.

No test covers any of these handlers, and none was added — the dead-code bug is
exactly what a request smoke test would have caught. Recorded in
`.work/backlog.md` rather than expanded into this change.

Model, `_resolve_decision` (device > client > global), and ingest tier logic
already supported three tiers.

Validated: `manage.py check` clean; `ruff check` on `views.py` reports 45
pre-existing findings and none new in the edited ranges. Not deployed; no data
written.

### Subject granularity — settled 2026-08-10, measured

Findings do not carry a version, so version scope was derived by joining each
finding's device+title back to the installation it was emitted from. The join
was exact: `install_not_matched` 0, `matched_but_no_version` 0, and all seven
`by title` figures above reproduced.

| type | open | by title | **by (title, version)** |
| --- | --- | --- | --- |
| vulnerable_software | 1,403 | 17 | **54** |
| eol_runtime | 630 | 106 | **123** |
| whitelist_suggestion | 131,073 | 1,631 | 9,564 |
| unauthorized_remote_access | 522 | 5 | 126 |
| suspicious_name | 383 | 5 | 5 |
| known_malicious_hint | 128 | 11 | 42 |
| unauthorized_av | 45 | 2 | 11 |

7 of 17 vulnerable titles carry multiple installed versions (one has 28); 10 of
106 EOL titles do (max 3). Collapse total 1,777 -> **1,831**.

**Decision: `vulnerable_software` and `eol_runtime` bind to product+version;
the other five bind to product.** A CVE applies to a release and an EOL date is
a release's, so title scope cannot distinguish patched from unpatched — which
is fatal, because patching is the remedy those two findings exist to prompt.

An earlier proposal to bind all seven to product now and re-subject the two
later was rejected by the user: build it once, correctly. That is the right
call, and it makes the evaluators part of this work rather than a follow-up —
binding to version while the evaluator still decides by title would produce a
finding that claims to be about a release but was not.

### What each evaluator needs to become version-aware

* **`vulnerable_software` — no new data required.** `matcher.py` already
  computes version filtering (`_parse_version_prefixes` at :184,
  `_filter_by_version_prefix` at :287) and then **discards it**: `cve_match` is
  keyed `(tenant_id, canonical_name, cve_id, match_kind)` at :269. The prefix is
  also parsed from the *title text*, so the installed `version` column is never
  read. Fix is to move the matcher's unit of work from title (21,370) to
  product+version (40,541) and key `cve_match` on the version.
* **`eol_runtime` — missing producer.** 0 of 40,541 `software_versions.eol_date`
  populated and no EOL connector exists in `ingest/`; `intel_ingest_status`
  registers nvd, cisa_kev, epss, winget, chocolatey, otx, abusech_mb,
  abusech_tf and nothing for lifecycle. Needs an `endoflife.date` connector.
  User authorized acquiring the data ("if we need more data let's plan on
  getting it"). Until it lands, `eol_runtime` keeps firing on title patterns;
  it must **not** be emitted at version scope before then.

### Implementation checkpoint — 2026-08-10, local, not committed, not deployed

Built:

| artifact | what |
| --- | --- |
| `sql/migrations/076_catalog_finding_subject_uuids.sql` | `product_uuid` / `version_uuid`, unique, minted. PKs and the 489,347-row FK untouched |
| `sql/migrations/077_cve_match_binds_to_version.sql` | `cve_match.software_version_id`; replaces unique index `cve_match_scope_idx` with one including the version, `NULLS NOT DISTINCT` |
| `sql/migrations/078_endoflife_corpus.sql` | `intel.eol_products` / `intel.eol_releases` (natural keys, no tenant) + `operations.eol_product_map` |
| `ingest/intel/endoflife.py` | corpus fetch, API v1, 462 products, per-product failure isolation |
| `ingest/intel/eol_match.py` | projector: mapping + longest-cycle-prefix -> `software_versions.eol_date` / `eol_source`, with a clear path |
| `ingest/intel/matcher.py` | unit of work title -> product+version; version no longer discarded at INSERT |
| `apps/core/migrations/0129_software_finding_subject_types.py` | `software_product` + `software_version` on `Finding.SubjectType` |

Wired: runner, scheduler (`INTEL_CATALOG_SCHEDULE_HOURS`), `/run/intel-endoflife`,
startup catch-up plan, `INTEL_ENDOFLIFE_ENABLED`, module docstring.

Decisions taken while building:

* **`cve_match.software_version_id` NULL is meaningful.** A version-agnostic CPE
  (`*`, `-`, absent) genuinely affects every release, so those rows stay
  product-level explicitly instead of being fabricated onto a version.
* **`operations.eol_product_map` has no RLS**, matching its neighbours
  `cve_match` and `safety_signal` — tenant-scoped tables in this SQL path carry
  a `tenant_id` and no policy, unlike the Django-managed ones. Recorded in the
  migration as a known three-table asymmetry, not resolved here.
* **The mapping table ships empty.** `eol_match` logs a warning rather than
  reporting success, and `eol_runtime` stays title-scoped until mappings exist.
  Seeding candidates should be derived by measuring the real catalogue against
  the 462 corpus products, not invented.

Near-miss worth keeping: three guesses at the existing `cve_match` unique
constraint name were all wrong (it is `cve_match_scope_idx`, an index not a
constraint). `DROP ... IF EXISTS` on a wrong name is a silent no-op, so 077
would have applied cleanly and left the old key enforcing the old behaviour.

Validation: ruff clean on all new modules; `matcher.py`, `main.py`,
`software_findings.py` and `views.py` carry the same findings before and after
(3, 42, 8, 45), none new; `manage.py check` clean; no migration drift; template
compiles; `git diff --check` clean.

**Rehearsed against production 2026-08-10, all five SQL migrations in one
transaction, rolled back.** All applied without error. `product_uuid` 21,395
rows / 21,395 distinct / 0 null; `version_uuid` 40,578 / 40,578 / 0. Migration
079 closed **134,184** rows (the 134,484 in the table above was measured earlier
the same day; the catalogue also grew 21,370 -> 21,395 products in that window,
so this is ingest drift, not a discrepancy). Afterwards the only device-scoped
software findings left open were `rare_recent` 2,658 and
`install_path_suspicious` 398 — exactly the two that are supposed to stay, which
confirms 079's name list is both correct and complete. Rollback verified: the
`product_uuid` column is absent again.

Not covered by the rehearsal: `v_device_software_exposure` parsed, created and
executed but returned **0 rows**, because no finding has been re-subjected yet.
Its join logic is therefore unproven until the emitter runs. The connector has
still never executed against the live API.

### Steps

0. ~~Fix authorization at all three tiers~~ — done, see above.
1. **Retracted: do not convert the `catalog` PKs to uuid.** ADR-0012 §7 exempts
   global reference corpora, and the 2026-08-10 amendment placed software
   beside `intel.cves` precisely so it is not shaped like the owned-entity
   store. That corpus is keyed naturally — `intel.cves.cve_id text PRIMARY KEY`,
   `intel.cpes.cpe23 text PRIMARY KEY` — and the catalog already has its natural
   keys under unique constraints. Retyping its PKs would make it the only
   reference corpus wearing entity-store keys, repeating the error the
   amendment corrected, and would touch the 489,347-row installation FK for no
   gain.

   **Replaced by:** add a stored `uuid` column to `catalog.products` and
   `catalog.software_versions` (migration 076) as the stable handle the
   polymorphic `findings.subject_id` needs. PKs and FKs untouched. Stored and
   minted once rather than derived from the natural key, because publisher
   aliases collapse the long tail over time (84% of installs covered, 6% of
   distinct publishers) and a derived id would silently re-identify products on
   every alias addition — ADR-0012's "nothing is lost without when and why".
   A stored id makes that collapse an explicit merge instead. Postgres is 16,
   so `gen_random_uuid()` is core; pgcrypto is still not installed.
2. Add `software` to `Finding.SubjectType` (today: client, device, client_user,
   source_binding, collector_instance).
3. Re-emit the seven intrinsic types at `(client, title)`; close the 134,484
   device rows with a recorded cause.
4. Build `operations.v_device_software_exposure`; revoke DML from runtime
   roles per `operations/AGENTS.md`.
5. **Rewire the ~10 `views.py` sites** filtering software findings by
   `subject_type = 'device'`, plus `findings_queue.html:165`. Without this the
   device pages go empty. Not optional; the bulk of the work.
6. ~~Correct the Limit 2 text~~ — done. It was only in
   `ingest/software_catalog.py`; `074_software_catalog_entities.sql` never
   carried the claim, so the applied migration was not touched. The docstring
   now records the measured 0 multi-version (device, title) pairs and marks the
   collapse theoretical rather than active loss.

### Process note

Three times in this task a plan was built on an unmeasured assumption and
retracted (MATCH SIMPLE, publisher alias operator, client-blind collapse).
Measure before asserting, and do not treat agreement with an existing document
as corroboration — both can share the same error.

---

Track: **Operator experience — five tracks (2026-08-06)**

The ADR-0010 entity track (E1-E6) is complete and deployed; its record is
retained below. Five tracks follow, set by the user.

## T1 — Page load times

Measure first, then fix. `pg_stat_statements` is available but not loaded, and
loading it needs a Postgres restart; the page set is finite (79 routes, ~40
operator-facing), so each page's SQL is timed directly instead.

Known heavy candidates before measuring: the patching posture CTE
(`views.py` ~5020), the software surfaces over
`software_installations_current` (475,672 rows / 1,394 MB), the findings queue
(261,116 rows / 239 MB), and the client workspace, which fans out per client.

**T1 comes first because T2, T3 and T5 all add queries and content to pages.**
Optimising after that is harder than establishing the baseline now.

## T2 — Click-through everywhere

Every count becomes a route to the rows behind it: client device counts to a
filtered devices page, finding counts to a filtered queue, source counts to
that source's devices. Templates plus small view filter additions. The
`?key=` filter added to the merge queue in 0.114.1 is the pattern — the filter
is shown, escapable and preserved.

## T3 — Details displayed on pages (in columns)

Which columns each list shows, sortable and filterable, per the existing
convention that every table is both.

## T4 — Software classification and categorisation

The only track with an engine rather than a surface: categorising titles in
`ingest/inventory/` and the software decision surfaces. Independent of the
other four and can run in parallel.

## T5 — Overall UI

Track UI-2 in `operations/BLUEPRINT.md`. Scope to be set by the user; not
started from this plan.

## Current position

**Entity instantiation — `asset` (built locally, not committed).**

`promote_candidate` in `operations/apps/core/entity_candidate_decisions.py` is
the missing verb: `attach_candidate` required a target entity that already
exists, and the only two anchor-creation paths in the platform mint a `device`
or a `client` by reusing that typed row's UUID, so a class with zero entities
could never gain its first one.

Files: `entity_candidate_decisions.py` (promote + shared
`_link_candidate_to_entity` extracted from attach), `generic_admin.py` (view +
`can_promote`), `config/urls.py`, `templates/entity_candidate_detail.html`,
`apps/core/tests/test_entity_promotion.py`.

No schema change. No automatic caller — operator-invoked only. Safe against
existing surfaces because `v_entity_summary` LEFT JOINs `devices`/`clients` and
its label already falls back to `'<class> entity'`, i.e. it was built for
entities that are neither.

Guard: promotion is refused for any class whose entities keep a typed record,
asked of the data (`class_supports_promotion`) rather than by listing class
names, so it is a structural invariant and not an ADR-0012 §6 domain mapping.

Validated: ruff clean, `manage.py check` clean, no migration drift, 6 new
tests, 48 core tests pass (2 Postgres-integration skips), template compiles,
URL resolves. Not deployed; no data written.

**Not covered by this work, measured 2026-08-07:**

- **software has 0 observations, 0 candidates, 0 source links** against 484,636
  rows in `software_installations_current`. It never enters the candidate
  pipeline, so `promote_candidate` does nothing for it. Software identity is
  *derived* (`publisher, product, version` is deterministic and rebuildable) =
  a projector, not a promotion.
- Software is gated on unscoped entities. Verified on production: the
  `tenant_isolation` policy is `FOR ALL` with
  `tenant_id = current_setting(...)` in **both** USING and WITH CHECK,
  `tenant_id` is NOT NULL, and `ck_entities_scope_owner` permits only
  `tenant`/`client`. A NULL tenant would make the row invisible to every role.
- `user` class has **no `entity_type` row at all**.

Software scale is settled and is not a partitioning question: 4,863 publishers
+ 20,876 products + 40,261 product+versions = ~66,000 entities ≈ 27 MB at the
measured 417 B/row, and 484,636 installation relationships ≈ 320 MB at the
measured 660 B/row, against a 46 GB database. All eight E4 relationship tables
exist and hold **0 rows**, so software would be that engine's first real use.

Open, not concluded: `publisher_aliases` (56 rows) matched **0 of 4,863** raw
publishers on a literal case-insensitive match. The regex check did not
complete. Settle it by aggregating distinct publishers into a CTE first
(4,863 × 56, not 484,636 × 56).

T1 (page load times) is paused at the software page fix in 0.115.0.

### E6 remaining scope — resolved 2026-08-06 (ratified in ADR-0013 amendment)

The phase line reads "obsolete compatibility columns/readers" and was never
enumerated. It covers two halves; only one is actionable.

**Columns — closed, they stay.** Codex design history framed the flat
`operations.devices` cache columns as transitional ("validating
cache/projection equality until the compatibility columns are dropped"), which
conflicts with this track's later entry that they are permanent. Measurement
settles it without needing the preference: `os_group` and `device_type` have
**0 of 5,298** effective-contract rows and no source to give them one — the
projector derives them instead. Dropping them is not achievable until that
source is built, which is separate work and not an E6 gate. Supporting
figures, measured 2026-08-06: `os_family` 5,244/5,298 effective coverage,
`device_role` 4,721, `os_name` 4,720, with **zero** mismatches wherever a
value exists; flat read 4.7 ms against 362.9 ms pivoted from the contract.
The single-writer projector plus its ratchet test is therefore the permanent
enforcement, not an interim one.

**Tables — this is E6's remaining work.** Measured 2026-08-06:

| relation | rows | code readers | note |
| --- | --- | --- | --- |
| `client_links` | 320 | 12 | **exact twin of the retired `device_links`.** `entity_source_links` holds 320 `client` rows — 1:1. |
| `client_candidates` | 9 (8 open) | 6 | **keep — not debt.** The preventive workflow that makes client merging unnecessary: its *map* action attaches a differently-named source group to an existing client before a duplicate can be created. Zero duplicate clients across 76 confirms it works. See the ADR-0012 amendment. |
| `merge_candidates` | 0 | 3 | **surface with no producer** — nav badge, workspace section and admin, but nothing writes it. See backlog; decide whether the feature is wanted before dropping. |
| `source_bindings` | 5 | 28 | duplicates `source_instances` (also 5); most readers, least urgent |
| `ninja_device_detail_current_shadow` | 5,499 | 6 | **keep — not debt.** Adapts `entity_observation_current.canonical_data` JSON into a typed columnar contract, which is the same pattern as `v_device_source_link`. Retiring it would push the JSON extraction into 6 readers. |
| `ninja_device_health_current_shadow` | 5,499 | 2 | keep, as above |
| `ninja_device_seen_daily_shadow` | 357,669 | 3 | keep, as above |
| `device_agent_presence_current_legacy` | 0 | 0 | dead matview — dropped in 0124 |
| `source_health_current_legacy` | 4 | 0 | dead matview, superseded by `source_health_current` (5 rows) — dropped in 0124 |
| `client_user_links` | 0 | 2 | **not an E6 table.** Data structure for the unbuilt Users capability — see below. |

**E6's table list is closed — none of the eight was compatibility debt to
retire beyond the two link tables and two dead matviews already done.** `device_links` and
`client_links` are retired; the two dead matviews are dropped;
`merge_candidates` was a missing producer, now fixed; the three shadow views
and `client_user_links` are not compatibility debt at all. `client_candidates` and `source_bindings` both stay: the
first is the preventive client workflow (ADR-0012 amendment), the second
carries the collector and schedule dimension that `source_instances` does not.

**E6 is complete.** Entity anchors required (`322d2a4`), competing attachment
authority retired (`device_links` 0.111.0, `client_links` 0.112.0),
compatibility columns closed by ratified decision, and the compatibility table
list resolved.

**Why the shadow views stay.** They were listed for retirement because the
name implies a temporary duplicate. They are not: each adapts the generic
observation store's JSON into a typed columnar contract in one place, exactly
as `v_device_source_link` does for source links. Retiring them would duplicate
the JSON extraction across 11 readers. Renaming to drop "shadow" was
considered and rejected — touching 11 readers for a naming improvement is the
kind of churn that silently broke `device_merge.html` earlier in this session.
Documented here instead so they are not re-listed as debt.

**Correction on the shadow views.** They were listed as empty because the
inventory joined `pg_stat_user_tables`, whose `n_live_tup` covers tables only
and silently reports 0 for every view and matview. Counted directly they hold
5,499 / 5,499 / 357,669 rows and are working correctly — they are the *new*
path wearing legacy names, not abandoned debt. Nothing is broken there, so
they drop down the order rather than up it. Count a view before calling it
empty.

### Deployed this session

| commit | change | verified |
| --- | --- | --- |
| `c3dcd9d` | os_name to os_family becomes data (migration 0118); os_family returns NULL not 'Unknown' | 123/123 os_name values identical; 13,716 stale `Unknown` claims cleared to 0 |
| `7e57ba3` | device cache projector is sole writer of five columns; nine producer writes removed | live run matched dry run exactly; all five columns 0 changes after convergence |
| `803417d` | node_class taxonomy becomes data (migration 0119); evidence counter corrected 379 to 33 | `device_type` 0 changes live, so table-driven derivation is behaviour-preserving |
| `79f4462` | mapping-table loads contained in a SAVEPOINT | fixes a defect 803417d shipped; clean startup, no `InFailedSqlTransaction` |
| `322d2a4` | Client/Device entity anchors required (migration 0120) | both columns NOT NULL; promotion path proven by a rolled-back transaction |
| `e52eb20` `aa500f7` `d8243b6` `3c7d9a1` | records: findings sanitization closed, backlog findings, ADR-0013 amendment, device_links rule | docs only |

### Decisions closed this session

- **Findings sanitization: no code required.** Of 139 matching findings, 43 are
  publisher strings containing vendor URLs, 95 are Hudu clickthrough links, 16
  are real serials across 14 findings. No exposure path exists — no
  finding-detail route, no API, and `operations.findings` grants SELECT only to
  `metabase_ro` and `operations_readonly` under forced RLS.
- **`v_device_current` retracted** (ADR-0013 amendment). It was never built so
  never had consumers; `v_device` predates ADR-0005 and is the read surface;
  release 0.64.0 recorded that the flat columns stay as a cache; and pivoting
  from the effective contract is ~70x slower (5.5 ms vs 383.6 ms).
- **The flat Device columns are permanent** as a single-writer projection. The
  defect was nine producers, not the cache.
- **The typed layer tables stay.** No retirement pressure now that
  `v_device_current` is retracted.

### Deferred, with reasons recorded in `.work/backlog.md`

Unscoped entities (not an E6 gate; needs an RLS policy replacement on a
forced-RLS table); write-only layer tables and
`agent_instance_field_history` at 0 rows; silent `conflict = false` on genuine
source disagreement; the 33 unevidenced form factors; the remaining hardcoded
mapping tail.

## Authority and checkpoint

- The user authorized autonomous implementation, commits, both pushes, and
  their coupled Portainer deployments. Validation should remain basic and
  proportional: syntax/static checks, migration consistency, and basic
  deployed version/health/HTTP-500 and aggregate behavior checks. The user
  explicitly waived further local Docker rehearsal for this phase.
- Release `0.103.0`, commit `0f32922`, is deployed on both remotes. All enabled
  collector families use the generic source-record current/change-history
  contract. The verified cycle wrote zero legacy Ninja detail/health snapshots.
- Existing unrelated backlog, instruction, design, and probe-file changes are
  preserved and excluded from release commits.
- Agent Compliance redesign/cleanup and legacy Ninja historical deletion/disk
  reclamation remain explicitly excluded. Existing typed patch, software,
  immutable activity, audit, notification, finding, and run-ledger semantics
  remain distinct from accidental poll-copy storage.

## Production sizing findings (aggregate-only, read-only)

- Generic source storage contains 30,088 stable current records, 29,240 active,
  57,955 retained material intervals, 341,130 daily rollup rows, and 695 compact
  snapshot-run rows. The measurement returned no identities or payload values.
- Expanding normalized top-level scalar/set members produces 428,425 current
  claim rows (417,931 active). Per-record claim medians are 5-20 by contract;
  p95 is at most 21 for the large namespaces and the measured maximum is 46.
- Attribute-level comparison, excluding unchanged projection-contract-only
  intervals, found 50,107 changed claim members in the latest seven-day window.
  Because Ninja health existed for only part of that window and rollout changes
  are recent, use a conservative 7,200-10,000 changed-member/day envelope.
- Projected claim-history additions are 216k-300k at 30 days, 648k-900k at
  90 days, and 2.63m-3.65m at 365 days. With a deliberately conservative
  256-512 bytes per heap-plus-index row, current claims require about
  105-209 MiB; history requires 53-147 MiB at 30 days, 158-440 MiB at 90 days,
  and 642 MiB-1.74 GiB at 365 days. WAL remains an estimate until a disposable
  scale benchmark: roughly 2-4x changed indexed bytes, or about 1.3-7.0 GiB at
  the 365-day envelope.
- Existing physical totals are 182.6 MiB generic current, 70.8 MiB generic
  history, 45.5 MiB daily rollup, and 0.7 MiB snapshot runs. Typed stores are
  materially larger but semantically intentional: activities 7.02 GiB, patch
  facts 864.6 MiB, software current 1.46 GiB, and software history 445.7 MiB.
- Initial claim history does not justify partitioning below four million rows
  per year. Use identity/open-interval B-tree indexes plus a time BRIN, retain
  closed claim history for 90 days in line with source material history, and
  retain compact daily rollups for at least 365 days. Revisit partitioning at
  10 million retained rows or sustained 25,000 changed members/day.
- Claim current rows must not receive heartbeat writes. They change only when
  an attribute value, supporting evidence, authority, or withdrawal changes;
  last receipt/contact remains inherited from the source-record current row.

## End-state acceptance

1. Every canonical client/device has a stable generic entity anchor without
   changing existing typed IDs or foreign keys.
2. One authoritative generic source link maps each attached stable source
   identity to an entity; compatibility links remain until all readers cut over.
3. Deployment-controlled definitions and mappings produce typed, sensitivity-
   classified current claims and attribute-delta history without per-poll
   duplication. Unmapped fields default restricted and remain visible by count.
4. Authority policy and audited operator decisions produce one rebuildable
   effective-value contract. Equal-authority conflicts are visible and never
   silently broken by recency.
5. Relationship evidence, canonical edges, decisions, candidates/events, and
   source-native events preserve provenance and withdrawal independently.
6. Generic read models and Operations admin pages expose entities, sources,
   evidence, claims/conflicts/effective values, candidates, relationships, and
   source health without source-name template branches.
7. Existing typed device/session/patch/software consumers move only when their
   effective projections have measured parity. Compatibility columns/tables
   and destructive cleanup remain separate final contracts.

## Delivery phases

### E1 — Generic entity and source-link kernel (`0.104.0`, complete)

- Add entity-class/scope registries and the tenant-scoped generic entity anchor.
- Add nullable unique entity anchors to Client and Device, backfill them while
  preserving typed primary keys, and keep typed tables authoritative.
- Add generic source-link current/history and generic candidate current/events.
  Backfill links from exact stable observation identity plus existing resolved
  client/device compatibility IDs; unresolved evidence remains unattached.
- Expose populated registries/entities/links read-only; keep empty candidate
  admin pages hidden until the E4 engine exists, per the engine-first UI rule.
- Expand entity-type capabilities required by ADR-0010. Add read-only Django
  admin visibility. Apply RLS, tenant-consistent uniqueness, least-privilege
  grants, and additive rollback-safe constraints.

### E2 — Attribute definitions and delta claims (`0.105.4`, complete)

- Add versioned attribute definitions, source-field mappings, identity/
  attribute authority policies, typed current/history claims, and withheld
  classification counts.
- Seed the normalized fields required for identity, lifecycle, session,
  operating-system, source health, and CMDB evidence; all unmapped fields are
  restricted and counted rather than silently trusted.
- Backfill roughly 428k current claims in bounded batches. Project only changed
  attributes on later material transitions; do not update claims for heartbeat-
  only polls. Add 90-day closed-history retention and threshold monitoring.

### E3 — Effective values and operator decisions

- Add audited single/set operator decisions, conflict rows, effective current
  values, and supporting-claim references.
- Implement deterministic policy selection: operator decision, authoritative
  eligible claims, then lower-tier claims. Equal-authority single conflicts use
  the definition policy (`retain_last_uncontested` or `unknown`).
- Add one projector and parity reports; connectors/resolvers may not write
  effective typed cache fields directly after promotion.

### E4 — Relationships, candidates, and generic source events

- Add relationship type/policy registries, unresolved external relationship
  evidence, canonical edges, supporting evidence, and audited include/exclude
  decisions.
- Promote candidate current/events to the generic review authority and migrate
  existing identity/client candidate workflows through compatibility views.
- Add immutable generic source events. Implement Ninja `NODE_DELETED` capture
  with protected actor metadata and source-withdrawal confirmation; never
  auto-retire a canonical entity.

### E5 — Generic read/admin surface and consumer cutover

- Add tenant-safe entity summary, source evidence, claim/conflict/effective,
  relationship, candidate, and source-health read models.
- Add Operations Admin landing/detail surfaces driven by registries, including
  restricted-value redaction and permission-checked audited reveal.
- Repoint APIs, exports, findings, notifications, evaluators, and approved typed
  readers to the shared effective contracts. Verify aggregate parity per reader.

### E6 — Contract and operational follow-up

- Make Client/Device entity anchors required only after full parity. Retire
  competing attachment authority and obsolete compatibility columns/readers in
  separately reviewable contract migrations.
- Keep Agent Compliance retirement and Ninja snapshot archive/delete/reclaim as
  independent backlog operations with their own backup/restore and destructive
  approvals. Audit/event retention and fleet-wide audit UI remain their defined
  follow-up tracks where not completed by E4/E5.

## After E6 — the track is complete; its named successors

The E1-E6 phase list ends here; there is no E7. E6's own text names what
follows, and all of it is deliberately outside the track because it is
destructive or belongs to another surface:

- **Agent Compliance retirement** — `ninja_agent_compliance`, 21 tables,
  **12 GB** measured 2026-08-06. Independent operation with its own
  backup/restore and destructive approval.
- **Ninja snapshot archive / delete / reclaim** —
  `ninja_core.device_snapshots` 7,961,331 rows at **14 GB**, and
  `device_health_snapshots` 7,487,737 rows at **7.4 GB**. Same conditions.
- **Audit/event retention** and **fleet-wide audit UI** — follow-up tracks
  where not completed by E4/E5.

For scale: the database is **46 GB**, so those three account for roughly
**33 GB**, about 72%. That is the largest single lever available and the
reason E6 pushed them out rather than absorbing them — each needs its own
backup, its own approval, and its own verification.

Independent of that list, the backlog carries the Users capability (0 rows
against 3,405 distinct users already ingested), consolidating software merge
proposals into `merge_candidates`, a continuous check that read models stay
read-only, and reconciling the merge queue with its findings.

## Basic validation and deployment

- `python manage.py check`, `makemigrations --check --dry-run`, targeted Python
  compile/Ruff/tests on changed files, and `git diff --check`.
- Verify aggregate relationship/candidate/event counts, RLS/policies,
  uniqueness and tenant consistency, decision audit triggers, idempotent event
  capture, and safe deletion-event withdrawal behavior.
- Commit only E4 release files, push `origin`, immediately trigger Portainer,
  push the identical commit to the mirror, then verify its version, migration
  application, service health, expected root status, and zero HTTP 500s.

## Current checkpoint and next action

Phase E1 is deployed as `0.104.0` / `5b2e873` on both remotes. Migration 0101
is recorded; production has 5,336 anchors, 24,924 current links and the same
number of open attachment intervals, with zero unanchored typed records,
duplicate stable links, or tenant/class mismatches. All five tables have
forced RLS and policies. Operations/ingest/Postgres are healthy, root/health
return 302/200, and there are zero HTTP 500 or ingest error markers. The first
Operations start deadlocked during 0101; its normal restart applied the
migration successfully and no recurring error remains.

E2 is deployed. The first `0.105.0` deployment applied
migration 0102, then PostgreSQL rejected 0103 table DDL while its newly seeded,
initially deferred foreign-key triggers were pending. The transaction rolled
back cleanly. Corrective release `0.105.1` validates those deferred constraints
before table-level RLS/ownership DDL. Migration 0103 then applied; its first
accelerated projector call wrote no claims and exposed unqualified
`pgcrypto.digest` under the restricted security-definer search path.
Corrective `0.105.2` proved that `pgcrypto` is not installed. Production
catalog measurement confirmed PostgreSQL's built-in
`pg_catalog.sha256(bytea)` is available; corrective `0.105.3` uses it without
adding a dependency and replaces the projector through migration 0105. The
full backfill then completed at 30,097 source records and 266,113 current/open
claim intervals. The immediate no-op exposed avoidable full-JSON re-hashing;
corrective `0.105.4` reuses the stored source `material_hash` plus version/link
metadata and replaces the projector through migration 0106.
Definitions/mappings and independent authority policy are deployment-controlled;
unmapped fields are restricted/count-only; current claims and per-member SCD-2
history are projected in separately committed bounded batches after migration;
heartbeat/contact timestamps remain on source current and do not create claim
writes. Basic Python, Django, migration-drift, retention, and diff checks
passed; the only Ruff findings were four pre-existing observation models
outside E2.

Corrective `0.105.4` / `032dc07` is on both remotes and deployed. Migrations
0104-0106 are applied and the one-time projection-hash refresh completed in
seven bounded transactions across 30,152 processed records. It recorded only
real intervening deltas: 71 inserted, 737 updated, and 36 withdrawn claims;
808 history intervals opened and 773 closed. The immediate steady-state pass
completed in 0.431 seconds with zero processed records or writes. Production
now has 30,103 source-current/projection/withheld rows, 266,184 current claims
(266,148 active and 36 withdrawn), and 266,921 history rows (266,148 open and
773 closed). There are zero duplicate current members, duplicate open
intervals, active/open-presence mismatches, tenant mismatches, or definition
type/cardinality mismatches. All five E2 tenant tables have forced RLS and one
tenant policy. Version is `0.105.4`; Postgres, ingest, and Operations are
healthy; root/health return 302/200; recent HTTP 500, traceback, and ingest
error counts are zero.

E3 is deployed as corrective release `0.106.1` / `7f07124` on both remotes.
The initial `0.106.0` deployment applied 0107, then PostgreSQL rejected 0108
because its initial dirty-key seed left deferred tenant constraints pending
before ownership DDL; the transaction rolled back and no typed consumer had
been cut over. Corrective 0108 forces the constraints before that DDL, and
migrations 0107-0109 are now applied.

The bounded initial projection completed in 363 transactions over 181,239
entity/attribute keys, producing 181,239 effective headers, 5,640 set members,
163,304 effective support rows, 168 visible conflicts, and 662 conflict-support
rows. The durable queue is empty; an immediate pass completed in 0.126 seconds
with zero processed records or writes. Duplicate, tenant/class/type/cardinality,
support, typed-value, set-status, and conflict-flag mismatch counts are all
zero. All eight E3 tenant tables have forced RLS and one tenant policy; the
tenant-scoped redacted view has exact 181,239-row parity. No operator decisions
exist yet, so production audit triggers were verified from the enabled catalog
contract without fabricating a customer-affecting decision.

Version is `0.106.1`; Postgres, ingest, Metabase, and Operations are healthy;
root/health return 302/200; current HTTP 500, traceback, ERROR, and CRITICAL
counts are zero. Both remotes match `7f07124`.

E4 was implemented for release `0.107.0`: deployment-controlled
relationship types and authority; unresolved relationship evidence; audited
include/exclude decisions; dirty-key effective edges/support; generic candidate
create/reopen/attach projection and atomic attach/reject services; immutable
restricted source events; and going-forward Ninja `NODE_DELETED` capture. A
read-only production measurement found 4,918 currently unattached source
identities (4,842 asset observed-only, 10 client observed-only, and 66 device
pending) for the bounded initial candidate projection. It also found 228
retained deletion events, all with actor IDs but none with a stable device ID;
the nested payload contains only a message. The deployment does not backfill
those historical events and never parses message/hostname text into identity.
Future deletion events withdraw evidence only when an exact stable device ID is
supplied and in order. Python compile, Django check, migration drift, focused
Ruff, nine contract tests, and diff checks pass; no local Docker rehearsal was
run. Next: commit the scoped E4 release, push both remotes with immediate
Portainer redeploy, then verify migrations, bounded candidate/no-op behavior,
aggregate relationship/event/RLS invariants, health, and current error counts.

The first `0.107.0` deployment applied migration 0110, then 0111 rolled back
because the relationship-type seed left initially deferred entity-class foreign
keys pending before ownership DDL. No E4 data or consumer cutover occurred.
Corrective `0.107.1` forces those constraints immediately after the seed and
adds an explicit E4 regression assertion. Next: validate, commit, push both
remotes with immediate redeploy, and complete the planned aggregate checks.

`0.107.1` then applied migrations 0111-0113 and both application containers
became healthy. The first manual bounded candidate transaction failed closed
before inserting rows because the SQL insert omitted the non-null
`latest_decision` and `latest_decision_reason` fields whose empty defaults are
Django-side only. Corrective `0.107.2` supplies both values for fresh installs
and migration 0114 replaces the already-deployed projector.

`0.107.2` / `6656385` is deployed on both remotes with migration 0114 applied.
The initial candidate projection created 4,890 candidates/events in 4.105
seconds: 4,842 asset observed-only, 10 client observed-only, and 38 device
pending. The immediate pass completed in 0.517 seconds with zero changes; the
relationship pass completed in 0.144 seconds with zero writes. Candidate
duplicate, observation, link/status, create-event, and tenant invariants are
all zero, and no eligible unmatched identity remains unprojected. E4 RLS and
trigger checks pass.

The runtime privilege check found schema-default named-role grants surviving
the original PUBLIC-only revoke, including protected `source_events` access by
`operations_app`. Corrective `0.107.3` adds migration 0115 and fresh-install
SQL that explicitly revoke all E4 table privileges from known runtime roles,
then reapply the documented least-privilege matrix.

Corrective `0.107.3` / `47bb68b` is deployed and mirrored. Migration 0115 is
applied and its deployed artifact matches the committed file. The exact ACL
matrix now passes: raw relationship evidence/history and protected source
events are ingest-only; Operations has only registry, decision, and effective
relationship access; no runtime role has DELETE. Both projectors are immediate
no-ops (candidates 0/0/0 in 0.375 seconds; relationships all zero in 0.012
seconds). Production holds 4,890 current candidates and 4,891 lifecycle
events; all six candidate invariants remain zero. All eight tenant tables have
forced RLS and one policy, and all seven E4 triggers are enabled. Both remotes
match, Portainer is active, every container is healthy, root/health return
302/200, and current HTTP 500, traceback, ERROR, and CRITICAL counts are zero.

Next: begin E5 by inventorying existing generic read models, Operations admin
surfaces, restricted-value permissions, and typed consumers against the E5
acceptance contract; then implement the smallest complete generic read/admin
slice and measured consumer cutovers without changing incompatible typed IDs.

## E5 checkpoint

- Production has 5,348 canonical entity anchors (76 clients and 5,272
  devices), five source instances, 24,980 current generic source links, 30,164
  current observations, 266,594 current claims, 181,380 effective values, 168
  conflicts, 4,890 candidates, and no current relationships. Fourteen active
  source-instance/type groups are sufficient for a row-based generic health
  surface; fixed per-class columns are not required.
- Existing attribute claim/effective views redact sensitive and restricted
  values, but the custom Operations UI has no generic entity/candidate/
  relationship surface. Source health is platform-keyed with fixed client and
  device columns, and Device Identity & raw reads observation JSON on ordinary
  GET.
- `operations_app` cannot read raw claim/history or E4 protected evidence, but
  still has direct `SELECT` on observation raw JSON and the underlying E3
  effective/conflict tables. Those grants cannot be revoked before named
  readers move to redacted views and an audited permission-checked reveal path.
- E5 will ship in reversible slices: E5.1 generic redacted read/admin and
  candidate workflow plus row-based source counts; E5.2 audited restricted/raw
  reveal and direct-table privilege cutover; E5.3 measured typed consumer
  parity/cutover. APIs, exports, evaluators, findings, notifications, and typed
  domain views move only when their output contract has measured parity.
- E5.1 release `0.108.0` / `6433f44` is deployed and mirrored. Migration 0116
  is applied. Its seven security-barrier views have the expected no-login,
  non-BYPASSRLS owner and exact app/read-only grants; ingest and Metabase are
  denied. Aggregate view counts match the underlying contracts (5,348 entity
  summaries, 24,980 source links, 168 conflicts, 4,890 candidates, 14 source
  instance/type groups, five source-health rows, and no relationships). Six
  authenticated read-only renders returned HTTP 200, containers were healthy,
  root/health returned 302/200, and current error counts were zero.
- E5.2 release `0.109.0` is implemented locally: default-denied audited reveal
  for observation and restricted claim/effective evidence, safe observation
  metadata for named write workflows, removal of raw Device GET reads, and
  revocation of obsolete observation-payload and E3 protected-table reads.
  Django check and migration drift pass; 11 focused E4/E5 contract tests and
  template loading pass. Next: complete the migration/privilege review and
  focused validation, commit, push/redeploy/mirror, then verify aggregate-only
  ACL, function, audit-contract, route, migration, health, and error behavior.

- E5.2 release `0.109.0` / `6d180bc` is deployed and mirrored with migration
  0117 applied and an exact artifact hash match. The reveal permission exists
  with zero direct/group assignments. Raw/canonical observation columns are
  denied to Operations, read-only, and Metabase; ingest retains them. E3
  protected tables are denied to runtime readers; only Operations can execute
  the two reveal functions. Device identity and generic entity GETs returned
  200 with zero raw observation SELECTs; reveal GET returned 405 with zero
  audit delta. No reveal was invoked. All stack containers are healthy,
  version is 0.109.0, root/health return 302/200, and current ERROR,
  traceback, critical, HTTP-500, privilege, and E5-table error counts are zero.
- E5.3 inventory confirms there is no data API beyond schema documentation;
  the generic entity CSV is redacted. Device presence/session/patch/software
  stores remain intentionally typed. Three independent legacy writers still
  select source precedence for Device role/OS caches (Ninja device ingest,
  resolver attribute sync, and evaluator role sync), and some older findings
  still embed sensitive serial/CMDB URL detail; those must be removed during
  E5.3 rather than treated as effective-contract consumers.
### E5.3 restated (2026-08-05, evidence-based)

The earlier parity table mixed two different kinds of column and the decision
gate rested on that conflation. Corrected:

- **Anchors need no work and the gate is closed.** `canonical_hostname`,
  `canonical_serial` and `canonical_vm_uuid` are written once at promotion
  (`resolver.py:733`, `:845`) and never updated: zero
  `UPDATE ... SET canonical_*` repo-wide, and zero `serial` / `vm_uuid` rows in
  `asset_field_history` across 5,273 assets despite an enabled trigger watching
  both fields. "Retain identity on withdrawal" is already the behaviour, so
  there is nothing to decide or build. The alarming hostname figure
  (28/5,186 exact) compared a write-once anchor against a live selection — a
  category error, not a blocker.
  Qualification (2026-08-05): the "zero `UPDATE ... SET canonical_*` repo-wide"
  half of this claim was a raw-SQL grep and missed
  `bootstrap_devices_from_ninja.py:169`, which updates `canonical_serial` and
  `canonical_vm_uuid` through the ORM. The gate still holds, but on the *other*
  half of the evidence: `asset_field_history` carries zero `serial` / `vm_uuid`
  rows across 5,273 assets under an enabled trigger, which is data evidence and
  independent of how many code paths exist. The command is manual-invocation
  only. Do not restate the code half without re-deriving it.
- **The work is five cache columns**: `os_name`, `os_family`, `os_group`,
  `device_role`, `device_type`. These are rewritten every resolver run, which
  ADR-0012 forbids. Their parity is strong and is the parity that matters:
  role 4,708/4,708, OS name 4,682/4,706, virtual flag 4,533/4,545.
- **Writer inventory: nine sites, not five.** The five-site list was derived by
  grepping raw SQL only. Re-derived 2026-08-05 by four methods — raw SQL, Django
  ORM, `pg_trigger`, and `pg_get_functiondef` — which found four more. Triggers
  and DB functions came back empty, so there is no database-side writer.
  1. `resolver.py:733` INSERT (promotion) — all five, `os_group` hardcoded
     `'Unknown'`
  2. `resolver.py:845` INSERT (promotion) — all five, same hardcoded `'Unknown'`
  3. `core/devices.py:278` `_sync_operations_device_roles` — device_role,
     os_name, os_family, os_group. Called from `devices.py:177` on the live
     Ninja collection path; arguably the primary producer
  4. `bootstrap_devices_from_ninja.py:169` — device_type, via the ORM
  5. `resolver.py:996` — device_role
  6. `resolver.py:1028` — device_type
  7. `resolver.py:1068` — os_name, os_family
  8. `evaluator.py:316` — device_role, `dev_claims.get("Ninja")` precedence
  9. `resolver.py:1078+` — facet propagation, writes `assets` / `os_instances`
     **from** the cache columns. Repoint, do not delete: removing the others
     without it freezes 5,273 assets and 5,255 os_instances.

  The two promotion INSERTs matter beyond the count: revoking `UPDATE` does not
  block `INSERT`, so a privilege-based cutover would have left both still
  stamping all five columns and looked like it worked.
  Out of scope: `evaluator.py:718` writes `lifecycle_status` (ADR-0011);
  `views.py:7590` writes `deleted_at`.
- **`os_group` and `device_type` have no effective-contract source.** Measured
  5,289/5,289 NULL for both. The projector derives them instead — `os_group`
  from `os_family` via `os_group_mappings`, `device_type` from entity type plus
  node_class — so the original "projector reads the effective contract for five
  columns" target was never achievable as written.
- **Target**: one projector reads the effective contract for `os_name`,
  `os_family` and `device_role`, derives `os_group` and `device_type`, and
  preserves the existing value where no claim is selected. The eight producer
  writes are deleted and facet propagation is repointed.
- **Enforcement is a test, not a privilege.** The projector runs on the shared
  `ingest.db` pool as the ingest role, so revoking `UPDATE` from that role would
  disable the projector along with the producers. A revoke would only add
  protection against ad-hoc `psql` writes, which self-heal on the next
  projection anyway — these are rebuildable cache columns and the blast radius
  of a violation is one cycle. Enforce with a ratchet test in the shape of
  `ingest/tests/test_no_hardcoded_domain_mappings.py`.
- **Findings sanitization: closed, no change required.** Measured 2026-08-05.
  139 findings match `serial` or a URL, and they are three different things:
  43 are false positives where the URL sits inside a software *publisher*
  string ("The Wireshark developer community, https://www.wireshark.org") and
  stripping it would corrupt the publisher name; 95 are Hudu deep links
  (`https://<tenant>.huducloud.com/a/...`) which are the operator clickthrough
  to the source record, so removing them makes `cmdb_asset_stale` and
  `cmdb_link_incorrect` non-actionable; 16 are real device serials, across 14
  findings, and in `shared_serial` the serial *is* the finding.
  No exposure path exists to sanitize: there is no finding-detail route (only
  the queue plus ack/resolve/snooze), `_detail_string` has no branch for either
  type so the queue renders nothing for them, there is no data API, and
  `operations.findings` grants SELECT only to `metabase_ro` and
  `operations_readonly` under enabled-and-forced RLS.
  An audited-reveal wrapper was considered and rejected: it would add a reveal
  surface for data that no screen displays.
- Also in scope, unchanged: run aggregate consumer parity before E6
  constraints.

#### E5.3 implementation checkpoint (2026-08-05, local, not deployed)

Done:

- Producer writes removed: `resolver._sync_device_attributes` lost its three
  derivation blocks (94 lines), `evaluator.py:316` lost its `device_role`
  UPDATE but kept the `device_role_conflict` finding, and
  `core/devices._sync_operations_device_roles` is deleted with its call site.
- Both promotion INSERTs now write neutral literals (`'unknown'`, `''`) instead
  of source-derived values. They must still name the columns because all five
  are NOT NULL; the projector fills them later in the same cycle.
- `bootstrap_devices_from_ninja` retired — orphaned since E3 per
  `SESSIONS.md:480`, docstring falsely claimed it ran from `entrypoint.sh`, and
  it carried a third form-factor classifier that returned `PHYSICAL` by
  default, the exact ADR-0005 bug.
- Projector wired into `resolve_all()` **before** `_sync_device_attributes`.
- `ingest/tests/test_device_cache_sole_writer.py` added. It parses INSERT
  column/VALUES lists positionally, so it flags a cache column only when it
  receives a bound parameter, not merely when a NOT NULL column is named.
  Verified by reintroducing one `%s` and confirming it reported exactly
  `device_type` at that line.

Correction to the target above: **facet propagation does not need repointing.**
It reads `operations.devices` — the projector's output — so it is a
cache-to-facet copy, not a second producer. It needed ordering, not a rewrite,
which removes the step that risked freezing 5,273 assets.

Deployed and verified (`7e57ba3`): the projector's first live run reported
`os_name 21, os_family 0, os_group 17, device_role 0, device_type 0,
rows_written 38` — identical to the dry run. Re-running the parity query after
it returned 0 changes on all five columns. 5,293 open assets, 0 out of sync
with `device_type`, and `os_instances.updated_at` matching the projection
timestamp, which confirms the ordering fix.

`node_class` to data is done in `803417d` (migration 0119, **not yet
deployed**). It also fixed `_like_to_regex`, which silently mishandled
backslash escapes and used unanchored `.search()` instead of LIKE's whole-string
semantics, and corrected `device_type_evidence_missing` from a spurious 379 to
the real 33.

Still open in E5.3: sanitize findings embedding serial / CMDB-URL detail, and
aggregate consumer parity before E6.

Unscoped entities moved to `.work/backlog.md` — investigated 2026-08-05 and
confirmed **not** an E6 gate, since E6 covers the tenant-scoped Client and
Device anchors and both are already fully populated.

#### Projector verified against production (2026-08-05, read-only dry run)

The projector's target SQL was run read-only against production before and
after an approved on-demand run of all five sources. Change counts, 5,293
devices considered:

| column | before | after | direction |
| --- | --- | --- | --- |
| `os_name` | 21 | 21 | trailing whitespace and `Microsoft ` prefix; effective is cleaner |
| `os_family` | 146 | **0** | all 146 were regressions to `Unknown`; cleared by withdrawal |
| `os_group` | 14 | 17 | all fixes, `Unknown` -> `Windows`, `os_family` already correct |
| `device_role` | 0 | 0 | — |
| `device_type` | 0 | 0 | — |

- **The `device_type` derivation is correct.** Zero changes across every device,
  including the hardcoded `NMS_` / `_VM_HOST` patterns. Those patterns are an
  ADR-0012 section 6 maintainability violation, not a correctness defect — the
  distinction matters, because the projector was previously described as unsafe
  to deploy.
- **The withdrawal path works.** All 13,716 `Unknown` `os_family` claims cleared
  to zero after the source runs, which is what took `os_family` from 146 to 0.
  This was the cutover gate and it is now closed by measurement, not by design
  argument.
- **The `os_group` fixes trace to writers 1 and 2** — devices stuck at
  `'Unknown'` because promotion hardcodes it and nothing revisits it.
- Net: the projector now produces 21 `os_name` improvements, 17 `os_group`
  fixes, and zero regressions on any column.
- Not yet verified: the projector's Python has never executed (the dry run
  transcribed its SQL into `psql`), steps 4-6 are untested, no test covers it,
  and the 30 devices counted by `device_type_evidence_missing` remain a mapping
  gap to close.
