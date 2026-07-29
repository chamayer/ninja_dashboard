# Active root work plan

Track: **Hudu integration — new data source**

## Status

- Discovery complete against the live instance (`amrose.huducloud.com`,
  profile `hudu` in `tools.json`).
- Full asset inventory measured: **12,180 assets across 21 layouts.**
- **Connector implemented** (uncommitted, working tree only):
  - NEW `ingest/connectors/hudu.py` — collector + card resolution.
  - NEW `ingest/device_map.py` — shared source-scoped device lookup.
  - NEW `ingest/tests/test_hudu_cards.py` — resolution regression tests.
  - MOD `ingest/source_observations.py` — `Hudu` fetcher registered;
    `_IDENTITY_ENTITY_TYPES` gate so non-identity sources skip
    `resolve_device_fast` and use a connector-resolved `device_id`;
    `canonical_extra` merge so connectors can contribute canonical fields.
  - MOD `ingest/sources.py` — `documentation` kind → `doc.asset`.
  - MOD `ingest/normalize.py` — `"hudu": "Hudu"` alias. Without it a config
    value of `"hudu"` would fall through `canonical_platform` unchanged, miss
    `_FETCHERS["Hudu"]`, and the source would be **silently skipped**.
  - MOD `ingest/main.py`, `ingest/config.py` — **interim** cadence split:
    documentation sources collect on `DOCUMENTATION_SCHEDULE_HOURS`
    (default 24) via `run_documentation_observations_once`, while agent
    sources keep the 4-hour cycle. Reason: Hudu is ~122 paginated requests,
    changes daily at most, and `load_sources()` orders by `s.name` so `Hudu`
    would precede and delay every agent source each cycle. Recorded in
    `.work/backlog.md` with its revert path; honouring
    `source_bindings.schedule` is the durable fix.
  - MOD `.env.example` — documented `HUDU_MAIN_API_TOKEN` placeholder.
  - All four existing sources keep identical behaviour: Ninja/S1/SC/LMI all
    map to identity entity types and stay on the agent cycle.

## Production state (applied)

- Source registered: `operations.sources.id=5`, `name='Hudu'`,
  `kind='documentation'`; shared instance (`client_id IS NULL`), enabled;
  binding `ba4744de-d813-484f-b53e-6eb63bdce422`, enabled.
- `HUDU_MAIN_API_TOKEN` present and non-empty in the host `.env`; name
  matches `config.api_token_ref`.
- **Dormant until deploy** — the running image has no `Hudu` entry in
  `_FETCHERS`, so every cycle skips it on the platform check.
- **Not yet runnable in production**: requires `operations.sources` /
  `source_instances` / `source_bindings` rows and `HUDU_API_KEY` in the
  server environment. Those are production data changes and need separate
  explicit authorization.

## Validation performed

- `python -m py_compile` passes on all changed modules; `git diff --check`
  clean.
- Existing ingest suite: **15 passed, no regressions.**
- `ingest/tests/test_hudu_cards.py` **skips on the workstation** (`httpx` is
  a container dependency, not installed locally). It has not been executed
  anywhere yet — it will run in the container image.
- **Offline validation against real data** — the real `_resolve_cards`
  source was AST-extracted and executed over 5,419 cached live assets plus
  the real 5,675-row Ninja `device_links` map:

  | Verdict | Connector | Independent DB measurement |
  |---|---|---|
  | divergent | 56 | 56 ✓ |
  | L13 stale | 143 | 143 ✓ |
  | L1 unlinked | 15 | 15 ✓ |
  | L13 unlinked | 252 | 224 Auvik-only + 28 cardless ✓ |
  | L13 `second_hand` | 224 | 1,391 any-card − 1,167 Ninja-card ✓ |

  Verdict buckets sum exactly to n (4,000 / 1,419) — classification is total
  and mutually exclusive. Invariant `device_id set ⟺ linked` held throughout.

- **Not validated:** no live run; the write path has never executed with a
  `doc.asset` entity type; findings and the unlinked surfaces are specced but
  not built.

## Goal

Ingest Hudu's documentation inventory into Operations, correlate it with
entities Operations already knows, and classify it from authoritative source
data rather than heuristics. No passwords, articles, procedures, or
write-back.

## Design — three separable layers

The earlier churn in this track came from conflating these. Kept apart, each
is independently decidable.

### 1. Ingest — unconditional, lossless, no decisions

Every Hudu asset becomes one observation, regardless of layout.

- `entity_type`: one new type outside the identity-signal set (proposed
  `doc.asset`) so it can never touch `device_links` — same posture as
  software.
- `entity_key`: Hudu asset id (globally unique, stable).
- `raw_data`: full payload including `fields[]` and `cards[]`.
- `canonical_data`: layout id/name, so per-layout decisions later are a
  query, not a re-ingest.
- `client_id`: from Hudu `company_id` via `client_links`, using the existing
  org-container pattern (as SentinelOne sites / LogMeIn groups).
- Archived assets ingested too, flag preserved — dropping them would
  silently discard evidence.

No allowlist. An allowlist silently discards whatever is not on it, which
conflicts with the never-drop-fetched-fields principle.

**One explicit exclusion: the People layout** (2,393 records), on
data-governance grounds — see the People section below. This is a deliberate,
recorded exclusion, not an allowlist: the layout must remain visible in the
layout inventory and in the Sources UI as *excluded by policy*, with its
record count, so an operator can see it is being skipped and why. A silently
absent layout would be exactly the hidden-drop failure the no-allowlist rule
exists to prevent.

### 2. Correlate — via integrator cards only, never names

Cards are keyed `(integrator_name, sync_id ?? sync_identifier)`. Ninja uses
an integer `sync_id`; Auvik uses `sync_id: null` plus a string
`sync_identifier`. Both shapes must be handled.

**Ninja cards** — `sync_id` *is* the Ninja device id, already the
`entity_key` of Ninja's own observations (`ingest/core/devices.py:487`):

```
sync_id → entity_observation_current WHERE platform='Ninja' AND entity_key=sync_id → device_id
```

Resolve every Ninja card, then cluster on resolved `device_id`:

| Case | Outcome |
|---|---|
| All cards → one Device | Attach `device_id` |
| Cards → 2+ *live* Devices | Attach nothing; finding (one page documents two machines) |
| Some cards → withdrawn observations | Normal — superseded Ninja records; ignore for attachment |
| No card → any live Device, asset not archived | Finding — documents a machine Ninja no longer manages |
| No Ninja cards | Not an error; see layer 3 |

**Convergence is tested on resolved `device_id`, never on names.** A Hyper-V
VM object is named independently of its guest OS, so name comparison
produces confident wrong answers (`QB`/`QBSERVER`, `Interest`/`INTERESTJ`,
`CP-CLD-EMP-TS`/`CP-CLD-EMP-TS1`). This is the "hostname alone never merges"
rule from ADR-0005. **No hostname/serial fallback matching anywhere in this
connector.**

**Non-Ninja cards — retained, but graduated provenance.** Second-hand data
is kept (discarding ~2,863 network devices would throw away real coverage),
but is never treated as equally authoritative:

- Marked with explicit provenance `second_hand` plus the originating
  integrator.
- Device linkage is *attempted* but **strong-evidence-only** — serial where
  present, or IP scoped within a single client and only when unambiguous.
  Never linked on `deviceName`, which is a generic `Device@<ip>` placeholder
  in 67% of cases.
- Records that do not link remain low-confidence inventory, visibly marked
  as such rather than mixed in with first-party data.
- One *aggregate* hint per unintegrated integrator (not per asset — 2,863
  findings would be noise) recommending it be considered for direct
  integration.

Measured Auvik signal quality (n=500): `deviceType` is `unknown` for **88%**;
`serialNumber` present 3.8%; `makeModel` 11%; `deviceName` generic
`Device@<ip>` 67%; `ipAddresses` 98%. An earlier claim in this track that
Auvik provides authoritative classification was based on a single sample and
is **wrong** — the corrected figure is recorded here so it is not repeated.

Hudu also stores only Auvik's *summary* payload; the card links out to
Auvik's `deviceDetail` endpoint. Direct integration would yield materially
richer data than this brokered view — reinforcing the hint.

### 3. Classify — from integrator taxonomy, data-driven

Classification normalizes **(integrator, native type) → Operations
category** in an admin-maintainable mapping table — not a layout-name
classifier, and not a code-level enum.

| Population | Count | Signal | Status |
|---|---|---|---|
| Ninja-carded | ~5,690 | `nodeClass` | Authoritative; `entity_type_for_node_class()` already maps it |
| Auvik-carded, real `deviceType` | ~340 | `deviceType` (printer/stack/ipmi/storage/…) | Usable, but second-hand |
| Auvik-carded, `deviceType=unknown` | ~2,520 | none — IP only | Low-confidence; unclassified by design |
| People layout | 2,393 | Not hardware — contacts | Definitive |
| **Manual-documentation tail** | **~1,240** | layout + patchy Vendor/Model | **Operator classification required** |

Honest coverage: roughly **69%** of the 12,180 arrive with a usable
classification. The remainder (~2,520 Auvik-unknown plus ~1,240 manual tail)
is genuinely unclassified and must be visibly so.

Observed `nodeClass` distribution: `WINDOWS_WORKSTATION` 3888,
`HYPERV_VMM_GUEST` 1399, `WINDOWS_SERVER` 824, `VMWARE_VM_GUEST` 267,
`HYPERV_VMM_HOST` 103, `LINUX_SERVER` 8, `MAC` 8.

The ~1,240 tail is **known-incomplete by design** — uncarded printers (281),
Applications (123), WAN (107), Network Devices (103), Special Role (92),
Mobile (73), plus small layouts. Nothing in the data classifies these
reliably. They require operator input seeded by admin-maintainable rules,
and must be operator-visible rather than silently bucketed.

## Measured inventory

| Layout | Total | Ninja-carded | Archived |
|---|---|---|---|
| 1 Computer Assets | 4,270 | 4,255 | 180 |
| 23 Auvik | 2,863 | 0 | 0 |
| 9 People | 2,393 | 0 | 45 |
| 13 Servers | 1,419 | 1,167 | 407 |
| 6 Printing | 294 | 13 | 1 |
| 11 Locations | 261 | 247 | 5 |
| 3 Applications | 123 | 0 | 3 |
| 2 Network Devices | 107 | 4 | 2 |
| 15 WAN | 107 | 0 | 7 |
| 5 Special Role Devices | 93 | 1 | 0 |
| 21 Mobile Devices | 73 | 0 | 0 |
| remaining 10 layouts | ~207 | 0 | ~2 |
| **Total** | **12,180** | **~5,690** | **~650** |

Cards are not confined to their layout — e.g. 224 Servers-layout assets
carry a non-Ninja card. Correlation logic is therefore per-card, never
per-layout.

Cached for local analysis (avoids re-hitting the customer instance):
`scratchpad/hudu_layout_1.json`, `hudu_layout_13.json`,
`hudu_layout_counts.json`.

## Decisions

- Single Hudu instance/API key for all clients.
- Hudu never participates in identity resolution and never writes
  `device_links`. Its identity claim is a pointer ("I am Ninja device 296"),
  not independent evidence. Ninja stays authoritative.
- Hudu never creates a Device. A machine documented only in Hudu is a
  finding (coverage gap), not an asserted entity.
- Locations (261) are ingested but never promoted — they are a Ninja mirror
  (`sync_type: "location"`), and Ninja locations are already ingested
  directly via `ingest/core/locations.py` → `ninja_core.locations`.
- Auvik gets its own integration later; Hudu only emits the hint.
- Classification mappings live in data, not code.

## Explicitly NOT needed

Investigated and ruled out during discovery — recorded so they are not
re-proposed:

- `AssetLink` table / `Asset` schema change / `Asset.source_observation` FK.
- Changes to `AssetType` choices or ADR-0005 semantics.
- Creating `Asset` rows with `device=NULL`.
- A per-source side table (`hudu_assets_current`). The
  `software_installations_current` precedent does not apply — software is a
  per-device attribute stream, not a managed entity.
- Any hostname/serial fuzzy matching.

These all followed from trying to make the uncarded tail into first-class
entities. Promotion to entities is deferred until the ingested data can be
inspected in the UI and the decision made with evidence.

## Hudu IPAM (networks / IPs / VLANs) — measured, not first-party

Hudu exposes a genuine first-party IPAM module (`/api/v1/networks`,
`/ip_addresses`, `/vlans`, `/vlan_zones` — full CRUD per the HuduAPI
wrapper; endpoint existence confirmed by control test against a bogus path
returning 404 HTML vs. these returning JSON). **But the content in this
instance is second-hand:**

| Table | Total | Provenance / coverage |
|---|---|---|
| networks | 198 | **195 Auvik-synced** (`sync_identifier` set); 3 first-party; 1 has a description; covers **3 companies** |
| ip_addresses | 9,726 | 4,615 linked to an asset; **0 fqdn, 0 notes**; covers **2 companies** |
| vlans | 1 | archived |

Conclusion: Hudu is **not** a first-party network source of truth — it is an
Auvik byproduct confined to 2-3 clients. Canonical network/subnet modeling
should therefore come from **direct Auvik integration**, not from Hudu.
Treat Hudu IPAM under the same second-hand rule as Auvik device cards.

Caveat: these endpoints do not paginate and the wrapper notes "server-side
limits may apply," so 198/9,726 are not proven complete.

**Scope boundary (recorded so it is not relitigated):** networks are carried
as *source-reported attributes* on records; a canonical Network/Subnet
entity is deferred to direct Auvik integration. Note IP-reported subnets are
mixed-prefix (`/24`, `/25`, `/12` observed), so a subnet can **never** be
inferred from an IP — the source must supply it.

**Decision — second-hand network data is used as a placeholder** until a
first-hand source arrives, consistent with the same rule applied to device
records. Conditions:

1. **Attribute/observation layer only — never canonical `Network` entities.**
   This is what keeps replacement cheap: a first-hand source supersedes the
   attributes. Promoting placeholders to canonical rows that other objects
   reference would turn the eventual swap into a migration with identity
   churn.
2. **Dedupe on the Auvik identifier.** The same Auvik network arrives by two
   paths — Hudu `/networks.sync_identifier` and the device cards'
   `relationships.networks[].id`. Verified same ID space: identifiers are
   base64 `<auvikTenantId>,<entityId>` and two 52-char values matched exactly
   across samples drawn from different Auvik tenants.
3. **Absence must be distinguishable from non-coverage.** Networks cover 3
   companies, IPs cover 2. A client with no network data must render as "no
   source covers networks for this client," never as an empty list implying
   the client has no networks.

## Linkage evidence rules — validated against the live database

DB read path (read-only, authorized):
`Invoke-DevTool.ps1 am-ch-01 ssh "docker exec ninja-postgres psql -U ninja -d ninja -c '<sql>'"`
(pattern documented in `docker-compose.yml`). Prefix tenant-scoped queries
with `SET operations.tenant_id = 1;`.

### Rule 1 — Ninja cards: direct `sync_id` lookup. Validated.

Measured by joining cached Hudu cards against
`operations.entity_observation_current` (5,734 Ninja rows):

| | Computer Assets (n=4,000*) | Servers (n=1,419) |
|---|---|---|
| No Ninja card | 15 | 252 |
| All cards resolve | 3,651 | 517 |
| Some resolve (superseded) | 79 | 507 |
| None resolve → stale | 255 | 143 |
| **Converge on exactly 1 Device** | **3,693 (92%)** | **981 (69%)** |
| **Diverge (2+ Devices)** | **29** | **27** |

\* cache truncated at a 40-page cap; layout 1 total is 4,270.

**Divergence is ~1% (56 assets)** — not the 86 the earlier name-based test
suggested. That test was invalid; convergence is measured on resolved
`device_id` only.

Algorithm: resolve each Ninja card; **ignore non-resolving cards** (they are
superseded Ninja records, not errors); from resolving+active cards take
distinct `device_id`; exactly one → attach; two or more → attach nothing and
raise a finding; none resolving and asset not archived → `hudu_asset_stale`.

### Rule 2 — Second-hand (Auvik) records: strong evidence only, low yield.

- **Serial: measured zero overlap.** 27 distinct Auvik serials (from 800
  sampled records, 3.4% coverage) matched **0** rows in
  `entity_observation_current`, `operations.assets`, and
  `ninja_core.devices`. Auvik covers network gear Ninja does not manage.
  Keep the rule anyway — it is free and correct when it fires — but expect
  no yield.
- **IP: permitted only when client-scoped AND unique within that client.**
  Measured ambiguity across 9,288 distinct Ninja IPs: 82.7% unique to one
  device, 13.3% on multiple devices in the same org, **4.0% (372) span
  multiple orgs**. Unscoped IP matching would therefore link devices across
  *different clients*. Never match on IP without client scoping, and refuse
  when the IP resolves to more than one device in that client.
- **Name: never.** 67% of Auvik `deviceName` values are generic
  `Device@<ip>` placeholders.
- **Expected outcome: most Auvik records remain unlinked.** That is correct
  and must be presented as such, not treated as a failure.

### Ninja NMS coverage gap (incidental finding)

`ninja_core.devices` currently holds only 3 NMS-class records
(`NMS_FIREWALL` 1, `NMS_OTHER` 1, `CLOUD_MONITOR_TARGET` 1). Hudu's
printer/appliance cards reference `NMS_PRINTER`/`NMS_APPLIANCE` sync_ids
(3688, 3691, 3640) whose `lastContact` is June 2025 — those Ninja devices no
longer exist. Confirms `hudu_asset_stale` has real signal, and that Ninja's
NMS-monitored inventory has largely gone away.

## New asset types (websites, certificates)

`Asset.asset_type` is `CharField(max_length=32, choices=[...])` with
**Django-level choices only — no DB CHECK constraint**
(`0050_layered_entities_schema.py:151`). Adding a type is an `AlterField`
migration on the choices list, not a structural change. So there is room.

However, per the deferred-promotion decision, websites and certificates do
not need entity promotion to be ingested — they can land as observations now
and be promoted once the classification design is settled. `service` would
plausibly cover websites; certificates have no existing fit and would need a
new value.

## Aggregation is an existing platform concept — Hudu extends it by one axis

`ingest/core/devices.py:424` already states: *"Ninja is an aggregator
carrying multiple streams — entity_type comes from node_class (agent.rmm /
vm.guest / vm.host / network.device / monitor.target). EVERY record is
observed, linked or not; unlinked rows get device_id NULL."*

The relay model is therefore already in production:

| Concept | Existing implementation |
|---|---|
| Which stream an observation came from | `entity_type` (`agent.rmm` direct; `vm.guest` relayed via hypervisor; `monitor.target` relayed via NMS probe) |
| Who relayed it | `canonical_data.parent_ninja_id` |
| Operator-facing provenance | `observed_via` in finding details (`evaluator.py:902`) |
| Unlinked relayed records | `device_id NULL`, still observed, never dropped |
| Relay ≠ proof of management | the vm.guest coverage rule |

**Hudu's delta is exactly one axis: cross-vendor aggregation.** Ninja relays
only its own data, so `platform='Ninja'` remains true for every stream. Hudu
relays *other vendors'* data, so collecting source (Hudu) and originating
source (Ninja / Auvik) diverge — and the `platform` column currently
conflates the two.

Consequence: this is an extension of a named, existing concept rather than a
new relay subsystem. The minimal change is to distinguish **collecting
source** from **originating source** on relayed observations, reusing the
existing `entity_type` / `observed_via` / unlinked-is-still-observed
patterns rather than inventing parallel ones.

## Observation shape — collecting vs originating source

**One observation per Hudu asset. Relay data is metadata on it, never
separate observation rows.**

```
platform    = 'Hudu'        -- collecting source, always
subplatform = ''            -- left RESERVED and unclaimed (see below)
entity_type = 'doc.asset'
entity_key  = <hudu asset id>
device_id   = resolved from the Ninja card cluster, else NULL
```

`canonical_data` carries relay detail, following the `parent_ninja_id`
precedent (relay provenance lives in `canonical_data`, not in schema):

```json
{
  "hudu_layout_id": 1, "hudu_layout": "Computer Assets",
  "provenance": "first_party",
  "relayed": [
    {"source":"ninja","key":"2848","resolved_device_id":"…","active":true,"integrated":true},
    {"source":"auvik","key":"MTMzODc…","resolved_device_id":null,"integrated":false}
  ]
}
```

`provenance` is **derived** from `relayed[]` (`second_hand` when every relay
is from an unintegrated vendor and the asset has no first-party content),
not a field that must be correct in advance.

### Why not a scalar `subplatform` column

Measured: **178 assets (L1+L13) carry cards from two distinct integrators —
all `auvik+ninja`.** A scalar column cannot express multi-vendor provenance,
and a filter like `WHERE subplatform='auvik'` would silently omit them.
It would technically work for today's data (all 2,863 Auvik-layout assets
are uniformly single-integrator, and the 178 are first-party docs that would
get `''`), so this is a redundancy/lossiness objection rather than a
correctness break. `subplatform` stays reserved and unclaimed — fixing a
wrong meaning onto it would require a data migration to reverse.

### Rejected: one observation row per relayed card

Fits the identity tuple neatly (`entity_key`=originating key,
`parent_source_key`=Hudu asset id) and would make each relay individually
withdrawable and dedupable. Rejected because a relayed card is a *pointer,
not independent evidence* — materializing it as its own observation invites
downstream logic to read it as corroboration. That shape becomes correct if
and when the originating vendor becomes a direct source, at which point its
own connector produces the rows legitimately.

### Measured card distribution (L1+L13, n=5,419)

| Cards | Assets |
|---|---|
| 0 | 43 |
| 1 | 4,336 |
| 2-3 | 927 |
| 4+ | 113 |
| 2+ distinct integrators | 178 (all `auvik+ninja`) |

Auvik layout (n=2,863): every asset has exactly one `auvik` card; none
cardless; no multi-integrator cases.

### Two additional findings identified

- **`hudu_duplicate_documentation`** — 95 Operations devices are claimed by
  2+ Hudu assets, near-universally the same machine filed under both
  Computer Assets and Servers (`L1/APP || L13/APP`, `L1/UPS || L13/UPS`).
  ~2% of the 4,569 claimed devices. Inverse of the divergence case.
- **Cross-vendor corroboration (positive signal, not a defect)** — the 178
  Ninja+Auvik assets are the one place second-hand Auvik data is
  independently confirmed by a first-party source. Worth surfacing as
  confidence, not just provenance bookkeeping.

## Connector shape — settled

- **Location: `ingest/connectors/hudu.py`**, same as every other source.
  Operations is source-agnostic; giving Hudu its own package would encode
  "Hudu is special." Instead the *framework* absorbs the variation:
  `source_observations.py::_write_observations` skips `resolve_device_fast`
  when the source's `entity_type` is not in the identity-signal set, and
  honors a `device_id` the connector already resolved. `fetch()` performs the
  Hudu-specific card resolution and returns rows with `device_id` set or
  None. Applies to any future non-identity source, not just Hudu.
- **`entity_type = doc.asset`**, new source `kind='documentation'` in
  `sources.py::_KIND_ENTITY_TYPE`. Follows the existing `<family>.<specific>`
  shape. Websites are a separate Hudu object type → `doc.website` if ingested.
- **Shared `load_device_map(source_name)` helper**, extracted from
  `software.py::_load_device_map` (which hardcodes `s.name='Ninja'`); software
  passes `'Ninja'`. Hudu needs it parameterized because the set of integrated
  integrators grows over time.
- **Lookup target: `operations.device_links`** (not
  `entity_observation_current`). Verified equivalent: Ninja links = 5,675 =
  observation rows carrying a `device_id`. 5,675 links → 4,900 distinct
  devices, confirming multiple Ninja records collapse onto one Device.
- **Snapshot:** all-pages asset fetch is a complete snapshot →
  `begin_run`/`complete_run`/`reconcile_complete_run`. **Any page failure ⇒
  no reconciliation**, so a partial fetch can never withdraw rows.
- **Counters** (resolved / diverged / stale / unlinked) logged and surfaced,
  never silently dropped.

### UI: matched records need no work

The device Raw tab (`views.py:1444`) selects `platform, entity_type,
observed_at, canonical_data, raw_data FROM entity_observation_current WHERE
tenant_id=%s AND device_id=%s AND active` — **no platform or entity_type
filter**. Any Hudu observation carrying a `device_id` therefore appears
automatically alongside Ninja/SentinelOne/LogMeIn/ScreenConnect, categorized
by the field-name-based `_RAW_FIELD_CATEGORIES` matrix.

Caveats: records with `device_id IS NULL` (diverged ~56, stale ~398,
unlinked second-hand) appear on no device page and need their own surface.
Hudu `raw_data` embeds `cards[]` with nested integrator payloads, so the
flattened raw view will be noisier than flat sources.

## Unlinked-record surfaces

The unlinked set is not one population — it splits by *why*, and the surface
differs accordingly.

| Reason | Volume | Surface |
|---|---|---|
| Stale (had Ninja cards, none resolve) | ~398 | Per-record finding `hudu_asset_stale` |
| Divergent (cards → 2+ live Devices) | ~56 | Per-record finding |
| Duplicate documentation | 95 devices | Per-device finding `hudu_duplicate_documentation` |
| Unintegrated vendor observed | 1 per vendor | Aggregate finding |
| Documented, unmonitored (manual tail) | ~1,240 | `/coverage/` section **+ one aggregate finding per client** |
| Second-hand, uncorrelatable (Auvik) | ~2,863 | **Separate** network-visibility surface |
| People | 2,393 | **Excluded from this track** (see below) |
| Locations | 261 | Ingested, never promoted (Ninja mirror) |

### Why the two browsable sections are split

Goal of `/coverage/` (per its docstring, "Compliance page: active
missing-agent findings"): **ensure things we manage are fully managed.**
Unit = a known Device; defect = a missing agent; action = install it; high
confidence.

- **Documented but not monitored** *matches* that goal — these are things
  deliberately written down whose management status is a real compliance
  question. Belongs on `/coverage/`, plus one aggregate finding per client
  ("N documented devices with no monitoring source") so it enters the
  findings workflow at an actionable granularity rather than as 1,240 rows.
- **Discovered but not identified** does **not** match. 88% have
  `deviceType=unknown`, 67% are named `Device@<ip>`. Placing that beside a
  confirmed "device missing SentinelOne" degrades the page's meaning to its
  least trustworthy row. This is the tier-3 network-visibility surface —
  scoped by client and source-reported network, its own route.

Per-record findings are reserved for bounded, individually-actionable cases
(~550 total). Inventory-shaped populations get browsable views, matching the
same reasoning that made the unintegrated-source hint aggregate.

Drill-through needs a route that does not exist yet (these records have no
device page): `/coverage/unlinked/?client=&reason=&source=`, sortable and
filterable per project table conventions.

### People layout excluded — data-governance decision

The 2,393 People records are **personal data** (names, and likely emails and
phone numbers). "Ingest all assets losslessly into `raw_data`" would place
PII at scale into `entity_observations` as a side effect of a device
integration — while ADR-0007's raw-data governance questions (allowed roles,
redaction boundary, tenant offboarding) remain open.

**Decision: exclude the People layout from this track.** Highest privacy
cost, zero value until a Users surface exists, and trivially reversible —
whereas ingesting PII is not. Revisit when the Users track opens.

## Open questions

1. **Websites** (`/api/v1/websites`) are a separate Hudu object type, not
   assets — Hudu-native monitoring data (uptime/SSL/WHOIS), no Ninja
   mirroring. In this pass or later?
2. **Managed Certificate** (9 assets) carries real expiry dates and
   `Asset Link (Where Installed)` — a natural `hudu_cert_expiring` finding.
   Same question.
3. **Promotion** — which layouts (if any) should produce first-class
   Operations entities. Recommend deferring until ingest + correlation ship.
4. **Divergence rate** — the true count of assets whose cards resolve to 2+
   live Devices cannot be computed from Hudu data alone; it needs a
   read-only query against `entity_observation_current`. No sanctioned path
   for that established yet.

## Next action

- On implementation authorization: draft the connector shape
  (`ingest/connectors/hudu.py`) — pagination, card extraction, the
  `(integrator, sync_id ?? sync_identifier)` key — plus the classification
  mapping table, for review before writing code.
- Commit and push remain separately gated.
