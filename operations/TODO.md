# Operations TODO

Per `Development/DEVELOPMENT.md`: Inbox / Backlog / Completed. This file is
module-specific; root `../TODO.md` keeps cross-repo items and pointers.

---

## Inbox

- [x] After device-list pagination/search ships, live-check
      `/orgs/uta/devices/` through Operations and compare response size/time
      against the previous large render. 2026-07-07: live response was 47,649
      bytes versus the previous 504,547-byte render.
- [x] Validate Operations container build/start on a Docker-capable host:
      migrations should run as `operations_migrate`, Gunicorn should run with
      `operations_app`, and `/healthz` should pass on `127.0.0.1:8091`.
      2026-07-07: confirmed via SSH as `amrose` with plain Docker commands;
      containers healthy, loopback health passed, migrations applied, and
      bootstrap counts populated.

---

## Backlog

### Parity blueprint (BLUEPRINT.md — Batches P1–P7)

- [x] Track E — entity model correction before P2. 2026-07-12: complete
      after THREE rebuilds. E1 gate exact; E2 deployed (migrations
      0024/0025, client-scoped identity, form-factor device_type,
      lifecycle transitions, presence matview all streams); E3 entrypoint
      bootstrap retired. Rebuild #1 (5,075 devices) was CORRUPTED — junk
      BIOS serial 'None' merged ~100 UTA servers; user caught it via
      console comparison. Fixes: `3a7168a` junk-serial guard, `11202d3`
      attribute sync, `00b0c05` same-stream dup separation +
      duplicate_platform_record finding (migration 0026), `efe8ecb`
      ambiguous-hostname individual promotion. Final verified: 5,168
      devices; UTA 110 Ninja server records → 110 devices; Ninja 5,458
      records → 4,842 devices (607 cross-stream merges) + 9 nameless
      vm.guests unresolved-visible; 39 dup findings. Commits `8b7c986`,
      `d50ad4d` (+ Codex `96f83b8..ba602ef`) + the 4 fixes.
- [x] Confidence-tiered dup collapse. 2026-07-13: hardware proof
      (serial / vm_uuid / MAC) merges duplicate same-stream records onto one
      device (reprovisioned VDI agents), stream-agnostic grouping, SC emits
      every live session + serial, promotion serialized via advisory lock
      (35 orphan devices from concurrent per-source resolver threads).
      Rebuild #5 verified: 5,120 devices, 0 orphans, UTA servers 110 =
      Ninja console, citrixapp26 7→1. Commits `3d6002f`, `ca22875`,
      `671e206`, `6870b28`.
- [x] Track 2 — P2 dispatcher (2026-07-14, `cd4d795`).
      ingest/notifications.py (suppression → rule match → cooldown →
      webhook/email/zendesk → audit); ingest/notifications_digest.py
      (daily); migration 0031 (`zendesk` channel + rules seed from
      legacy alert_rules DISABLED + version-drift state fix for
      AdminFinding/IdentityCandidate/NotificationRule); scheduler
      hooks conditional on NOTIFY_ENABLED/NOTIFY_DIGEST_ENABLED;
      manual endpoints /run/notifications/dispatch and /digest and
      /run/platform-evaluate; UI at /admin/notifications/ with
      enable/disable toggle + suppression list.
- [x] Track U — P3 UI framework slice (2026-07-14, `40992d1`).
      Shared includes: _pagination, _badges, _freshness, _tiles.
      Shared CSS in base.html (.filterbar, .filter-chip, .type-badge,
      .ops-table, .pager, .tile-grid, .freshness). Refactored
      findings_queue, org_devices, device_detail onto shared grammar;
      dropped ~150 lines of inline styling.
- [x] Track 1 — P1 gate audit (2026-07-14, `5fb3e24`). All 8
      sub-tracks (device promotion, device_scope, exemptions,
      missing/stale findings, source_failure guard, corroborated
      confidence, cross_client_conflict, lifecycle findings) verified.
      One bug fix: evaluator now writes platform_evaluator run_log
      rows so runs are visible. One 0-finding gotcha diagnosed and
      explained: `missing_required_platform` correctly returns 0
      because all 5,127 devices were `created_at` <24h ago from the
      Track E clean rebuild — the 24h gap_after_hours grace window
      is doing its job. Wait 24h and 3,754 findings will surface.
- [ ] Track C — client entity (BLUEPRINT Track C, priority before P2).
      2026-07-13: blueprint written (`3a4f10d`); batch C1 pushed
      (`500e419`): org observations per container from every source
      (Ninja orgs incl. empty, S1 /sites, LMI groups incl. empty, SC per
      instance), migration 0027 client_name_aliases / client_org_excludes
      / placeholder_org_names, hardcoded _PLACEHOLDER_ORG_NAMES retired,
      device resolver skips org rows. Batch C2 pushed (`954d635` +
      fixes `04e845c` / `a74f064` for two Django-default NOT NULL raw
      INSERT bugs): ingest/identity/client_resolver.py implements the
      strictly-exclusive ladder (id-link short-circuit → exact-name
      attach + mint client_link → collision detect → candidate), runs
      before device resolver with its own advisory lock; migration 0028
      adds client_candidates + client_links.created_at/created_reason +
      3 finding types (client_name_conflict, client_link_collision,
      client_unattached_group) + legacy import (50 aliases after
      dedupe from 267, 7 org_excludes). Verified on am-ch-01: TSK
      auto-attached on S1+LMI, Spencer/Glas attached via alias; 6
      open candidates (Silvercup, A.M.Rose Internal, DJ Direct GA,
      Gla, Silk Edge, Trimworx/Deco/BGG); 7 unattached_group findings;
      1 client_name_conflict drift finding. Batch C3 pushed
      (`a61c486` C3a data model + evaluator, `e760e2b` C3b evidence
      panel, `c5d1c56` C3c accept/map/exclude/fix + audit). C3a:
      requirement_profiles + requirement_profile_items with
      Django-partial-unique tenant-default; Client.requirement_profile
      FK; migration 0029 seeds "Standard" profile with 3 items from
      current global coverage_requirements (agent.rmm/Ninja,
      agent.edr/SentinelOne, agent.remote_access/LogMeIn) marked
      is_tenant_default. Evaluator: platform='any' wildcard via
      LATERAL subquery per-device, client-scoped rows REPLACE global
      rows (override index; COALESCE guards NULL client_id + empty
      override array). C3b: /clients/candidates/ queue + evidence
      detail (per-source records, sample devices, device-overlap
      signal, fuzzy suggestions vs display_name + aliases); nav
      badge via context processor. C3c: four POST endpoints with
      AuditLog; accept mints client with slug+display_name, attaches
      every source group via _attach_group_to_client, adds manual
      alias, instantiates chosen profile's items as per-client
      coverage_requirements. Verified on am-ch-01: migration 0029
      applied, Standard profile + 3 items seeded, /clients/candidates/
      renders 200, wildcard+override SQL executes cleanly (5,127
      devices matched). C.8 gate closed 2026-07-14 by scripted accept of
      Silvercup (exercises the view-layer code path). Fix `08d4b26`
      en route resolved a real bug the operator's first click would
      have hit: CoverageRequirement model missed `version`, DB
      column NOT NULL → NotNull violation during profile
      instantiate. Migration 0030 (state-only) syncs Django state to
      the pre-existing column. Round-trip: client mint
      (slug=silvercup, tenant-default profile), 2 client_links
      minted with created_reason='candidate.accept', 3
      coverage_requirements instantiated (Ninja/critical,
      SentinelOne/critical, LogMeIn/high), manual alias, candidate
      open → accepted, 14 S1 + 9 LMI org observations attached, 8
      device observations backfilled. **Track C is done.**
- [ ] `_infer_form_factor` guesses 'physical' from agent presence
      (parked 2026-07-14, ingest/identity/resolver.py:912). Contradicts
      BLUEPRINT E.7 ("device_type = form factor only; agent presence
      via agent_presence_current only"). When the only signal is
      `agent.*` (S1-only / LMI-only / SC-only device with no Ninja
      is_vm signal and no vm.guest observation), the resolver mints
      the device as `physical` instead of `unknown`. Zero impact
      today (all classified physical devices have Ninja is_vm=false
      backing) but wrong for future S1-only clients or agents on VMs
      Ninja doesn't see. Fix: return 'unknown' from the fallback.
- [ ] Coverage-requirement override semantics (parked 2026-07-14).
      Legacy tiered-replace (client tier fully replaces global tier) is
      restored in the evaluator. Optional Shape 1 extension for legit
      per-client add/remove: `CoverageRequirement.mode` enum
      `replace` (default) | `add` | `remove`. `add` rows always applied
      on top of the resolved tier; `remove` rows subtract from it.
      Enables "globals + FooAgent" and "globals − LMI" per-client
      cases without duplicating the base list. Not urgent — legacy
      duplicate-the-list workaround still works.
- [ ] Per-device exemption UI (parked 2026-07-14). Currently the only
      write path into `devices.exemptions` JSONB is auto from Ninja's
      `no_av_exempt` custom field (66 devices). Need a clickable
      "exempt this device from <entity_type>" affordance on the device
      page; audited. Distinct from suppressing a finding (which
      acknowledges a real gap without carving it out policy-wise).
- [ ] Suppress-this-finding action (parked 2026-07-14). Findings queue
      currently has ack; needs a "suppress" that creates a
      `SuppressionRule` scoped to that condition_key (optionally with
      expires_at), so future runs of the same condition don't re-emit
      notifications. AuditLog entry per suppression.
- [ ] Sweep other pages for hostname → device clickthroughs (parked
      2026-07-14). Same pattern as findings queue: templates that
      render a hostname without linking to the device detail page.
      Candidates: `findings_admin_health.html`,
      `client_candidate_detail.html` (sample_devices list),
      `merge_candidates_queue.html`, any hostname mention in
      dashboard/coverage pages. One template pass.
- [ ] Rename `agent_presence_current` → `device_presence_current`
      (parked 2026-07-14). Matview has covered all non-software entity
      streams (agent.*, vm.guest, vm.host, network.device, monitor.target)
      since migration 0025, and now carries `last_power_state`. Name is
      historically misleading. Migration: rename table + refresh function,
      grep-and-replace across evaluator / views / findings queue / coverage
      loaders. No logic change, one push.
- [ ] device_unenrolled UI polish (parked 2026-07-14). Findings queue
      renders these in the generic row shape today. Add a dedicated
      column set — power_state + days_since_last_seen + hypervisor
      host name — so operator can sort/filter "poweredoff = retire
      candidate" vs "poweredon = enroll candidate." Small view change.
- [ ] Auto-suggest profiles for global-fallback clients (parked
      2026-07-14). Remaining ~834 missing findings concentrate on the
      ~40 clients still without a `requirement_profile`. Heuristic
      scan: for each such client, look at actual agent coverage across
      their fleet; if most devices consistently have Ninja + S1 (say)
      but not LMI, propose a profile matching that shape. Operator
      accepts per-client via the profile picker. Would collapse a
      large fraction of the residual missing findings.
- [ ] ScreenConnect fetch returns exactly 1,000 sessions — suspected
      GetSessionsByFilter page cap; verify against SC console count and
      page if needed.
- [ ] Findings enrichment candidates from raw-payload audit: S1
      `infected`/`activeThreats`, agentVersion/isUpToDate, scanStatus
      staleness, encryptedApplications, machineSid (matching); SC
      LastBootTime, IsLocalAdminPresent, model/manufacturer. LMI stays
      hostname-only unless Central inventory API is added.
- [ ] Cosmetic: resolver attach path labels serial/vm_uuid matches as
      `hostname_strict`; fix labels when next touching resolver.
- [ ] Decide whether to restore cross-client same-hostname
      identity_candidates (Codex dropped creation; cross_client_conflict
      findings still cover detection).
- [x] P1 — Track 1 evaluator parity: coverage matrix, lifecycle findings,
      device promotion (span killed — promote on first observation),
      `/run/resolver` endpoint, client-page card accuracy + clickthrough.
      2026-07-09: live; UTA S1 servers 15/122 → 102/209; first full run
      findings_affected=1601.
- [ ] P2 — Track 2 notification dispatcher (`ingest/notifications.py`) +
      migration 0020 (rules created disabled) + review digest. Verify:
      webhook test delivery + cooldown.
- [ ] P3–P7 — software findings (3a), patching parity, UI parity (Track U),
      legacy cutover + deletion of `ninja_agent_compliance`. See BLUEPRINT
      batch table.
- [ ] Tune `cross_client_conflict` — 718 open findings, likely over-firing
      on generic hostnames shared across clients (e.g. `fileserver`).
      Needs policy decision: scope conflict detection to non-generic
      hostnames or require serial disagreement.
- [ ] Watch for `missing_required_platform` findings appearing as promoted
      devices age past gap thresholds (none on first run — created_at too
      young).
- [ ] gunicorn worker timeout (ninja-operations, one-off during matview
      refresh): if recurring, switch `refresh_agent_presence_current()`
      to REFRESH MATERIALIZED VIEW CONCURRENTLY (needs unique index).

### Platform implementation (BLUEPRINT.md — Batches A–E)

Operator action (do before Batch A1 — no code push):
- [ ] Add SOFTWARE_ADDED,SOFTWARE_REMOVED,SOFTWARE_UPDATED to INGEST_ACTIVITY_TYPES_INCLUDE in server .env on am-ch-01

Batch A1 — lifecycle/staleness foundations (Phases 1–2, ship together):
- [x] Phase 1: Django migration 0011 — software_installations_current three-state staleness (fixes active data-loss in refresh function)
- [x] Phase 2: Django migration 0012 — DeviceLink.missing_since + Device/Client lifecycle columns

Batch A2 — finding extensions (Phase 3):
- [x] Phase 3: Django migration 0013 — FindingType extensions + Finding extensions + new finding types

Batch A3 — new platform tables (Phase 4):
- [x] Phase 4: Django migration 0014 — CoverageRequirement, AdminFinding, QueueRegistry, IdentityCandidate, NotificationRule, NotificationState, NotificationEvent + RLS

Batch B — data sync + connectors (Phases 5–7, ship together):
- [x] Phase 5: ingest/core/devices.py — _sync_operations_device_links after _mark_missing_devices
- [x] Phase 6: new package ingest/identity/ — fast_path.py + resolver.py
- [x] Phase 7: Django migration 0015 (S1/SC SourceBindings) + dual-write to entity_observations in ingest.py

Batch C — evaluator + compliance rebuild (Phases 8–10, ship together):
- [x] Phase 8: ingest/evaluator.py — platform evaluator + schedule in main.py
- [x] Phase 9: ingest/agent_compliance/ingest.py — calls platform_evaluate() after AC run
- [x] Phase 10: Django migration 0016 — agent_presence_current materialized view

Batch D — web pages (Phase 11):
- [x] Phase 11: findings review page (/findings/) + admin health page (/admin/findings/health/)

Batch E — naming cleanup (Phases 12–14, coordinate with am-ch-01 .env update):
- [x] Phase 12: docker-compose.yml — rename ninja-ingest → operations-ingest
- [ ] Phase 13: Django migration 0017 — DB role rename ninja_ingest → operations_ingest
- [ ] Phase 14: Django migration 0018 — schema rename ninja_agent_compliance → agent_compliance
- [ ] Repo rename: ninja-dashboard → operations-platform (GitHub rename → local folder mv → Portainer stack git URL update → .claude memory path update). Low risk; GitHub redirects old URLs. Do last.

Operator action (no code push needed):
- [ ] Add SOFTWARE_ADDED,SOFTWARE_REMOVED,SOFTWARE_UPDATED to INGEST_ACTIVITY_TYPES_INCLUDE in server .env on am-ch-01

### M0 build

- [x] Ship server-side pagination/search for per-client device lists.
      Completed in `200c24f`, deployed through `cfa1767`, and live validated.
- [x] Live-validate the committed Operations container through Portainer:
      confirm commit `746770e`, startup migrations/bootstrap, `/healthz`,
      populated clients/devices, and same-password redeploy session
      preservation. 2026-07-07: validated startup health, migrations,
      bootstrap, and data counts. Browser session preservation still needs
      user-facing confirmation after a future redeploy.
- [ ] Browser-confirm Operations admin session survives a same-password
      Portainer redeploy.
- [ ] Decide whether to restore CI/pre-commit after resolving current Ruff
      lint debt, or keep it deferred until tests/lint policy settle.

### Activity → findings bridge (post-M0)

`ninja_activities.activities` is a rich finding signal that Operations
currently ignores entirely. The platform evaluator only reads
`entity_observations`; nothing reads activities. Key event types to wire up,
in priority order:

- [ ] **Security (immediate findings):**
      `SENTINEL_ONE_THREAT_DETECTED`, `SENTINEL_ONE_AGENT_DISABLED`,
      `SENTINEL_ONE_AGENT_INSTALLATION_FAILED`, `NODE_CLONING_DETECTED`,
      `ATTACHMENT_FILE_SUSPICIOUS`
- [ ] **Patch compliance:**
      `PATCH_MANAGEMENT_FAILURE`, `SOFTWARE_PATCH_MANAGEMENT_INSTALL_FAILED`,
      `PATCH_MANAGEMENT_PATCH_REJECTED`
- [ ] **Encryption compliance:** `BITLOCKER_DISABLED`
- [ ] **Device lifecycle:** `NODE_CREATED`, `NODE_DELETED` (faster than waiting
      for the device ingest cycle)

Architecture options when we get here:
  (a) Scheduled job scans recent activities and upserts findings directly.
  (b) Activity ingest writes to `entity_observations` with appropriate
      entity_type (e.g. `security.threat`, `patch.failure`) so the evaluator
      picks them up naturally — cleaner but requires new entity types.

### Operator UX — next up

- [ ] **Home page high-level cards:** fleet device count, active findings by
      severity, coverage gap summary (platforms missing), recent software
      decisions. Currently home.html is a stub.
- [ ] **Client page — agent presence / entity type cards:** show per-platform
      coverage counts (Ninja/S1/SC/LMI) from agent_presence_current with
      clickthrough to filtered device list. No representation of new entity
      types on the client landing page today.
- [ ] **Software review workflow:** decision summary tab on client page
      (approved/rejected/pending counts), bulk-decide by publisher.
- [ ] **Reusable scope selector:** extract org/device picker used in demand
      form into a Django template partial + view helper so findings filters,
      coverage requirement editor, and other views can include it without
      duplication.
- [ ] **Device detail page:** add agent presence section (which platforms
      observed this device, last seen per platform) and active findings list.

### Stack-wide (post-M0)

- [ ] Product direction: Operations is the operational data browser and
      control plane, not only an issue-resolution console. Build pages that
      help operators view current canonical data, source evidence, status,
      history, and workflow actions. Keep Metabase for exploratory BI and
      broad historical analytics.
- [ ] Browser-validate fleet overview dashboard. Committed as `8b452f7`,
      deployed via Portainer auto-update. Light browser check pending.
- [ ] Plan next domain browse/detail pages after clients/devices: candidates
      are users, software, sources/collectors, observations/evidence, and
      recent changes.
- [ ] Browser-validate client landing identity coverage section. Committed
      as `a8bf257`, deployed via Portainer auto-update. Light browser
      check pending.
- [x] Client landing identity coverage audit: decide which identities belong
      on the client summary page. Current page shows canonical client plus
      `client_links`; future candidates include source binding health, device
      source coverage, client-user identities, and unlinked external identity
      findings. 2026-07-07: approved as matching Operations' intent; compact
      summary section implemented locally.
- [ ] TLS reverse proxy in front of the whole stack (postgres/metabase/
      ingest/operations). Options: Caddy (auto-cert, easiest for LAN),
      Traefik (LE via DNS-01), nginx (manual). Currently everything is
      direct-Gunicorn/-Jetty HTTP. Once landed, set `OPERATIONS_HTTPS=1`
      in `.env` and re-enable secure cookies + HSTS. Blueprint §2
      explicitly deferred this; parked here as a conscious "later, not
      never."

### Process

- [ ] Tighten `/amr-ch-01_data/ninja-dashboard/.env` permissions to `0640`
      root:docker (currently 0644 world-readable). Coordinate with existing
      ingest/metabase/postgres containers so they can still read it after
      the mode change. Deferred until Operations container is deployed and
      verified, so we change one variable at a time.
- [ ] Audit `/amr-ch-01_data/ninja-dashboard/.env` for values with unquoted
      spaces and add quotes. Discovered when `INGEST_PATCHING_ENABLED_POLICIES`
      broke dash sourcing in the Operations entrypoint (worked around by
      only extracting OPERATIONS_* keys). Bash-based services (postgres,
      metabase) tolerated it; dash didn't. Nice-to-have, not blocking any
      current service.

---

## Completed

- [x] 2026-07-06: Added M0.6 observations, dead-letter table,
      `software_installations_current`, and refresh function migration.
- [x] 2026-07-06: Added M0.7 workflow/audit tables and admin wiring.
- [x] 2026-07-06: Added M0.8 RLS roles, policies, and grants migration.
- [x] 2026-07-06: Added M0.9 tenant/client-scope middleware and helpers.
- [x] 2026-07-06: Added M0.10 seed groups, permissions, taxonomy, and finding types.
- [x] 2026-07-06: Added M0 deployability role split for container startup.
- [x] 2026-07-06: Added module-level Operations build/session/TODO docs.
- [x] 2026-07-06: Added M0.11 bootstrap clients from
      `ninja_core.organizations` (`f13fc9b`).
- [x] 2026-07-06: Added M0.12 brand context, base template, and client
      selector (`aab87da`).
- [x] 2026-07-06: Added and then removed CI/pre-commit while lint policy was
      still unsettled (`1828e90`, `1e3a665`).
- [x] 2026-07-06: Added M1.1 bootstrap devices from `ninja_core.devices`
      (`afee1bf`).
- [x] 2026-07-06: Added device list/detail pages, findings queue, fleet view,
      merge candidates queue, policy editor, and summary sub-pages
      (`c32dae5`..`25584a0`).
- [x] 2026-07-07: Preserved Operations admin sessions across same-password
      redeploys (`746770e`).
