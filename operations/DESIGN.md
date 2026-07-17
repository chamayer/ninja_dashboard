# Operations Platform Design

Authoritative design reference for the Operations platform. Every
architectural decision made in design sessions lives here. Code should
reflect this document; when they diverge, update one or the other
explicitly — never let them drift silently.

---

## 1. Guiding principles

1. **Source-agnostic platform.** Operations does not belong to Ninja.
   Ninja is one source. The platform must work identically if Ninja is
   replaced by another RMM at any client or tenant.

2. **One observation pipeline.** All sources write to
   `operations.entity_observations`. No parallel observation tables.

3. **Modules provide data and configuration. The platform evaluates.**
   A module's job is to collect observations and define coverage
   requirements. It does not generate findings, route notifications, or
   manage acknowledgements — those are platform functions.

4. **Identity resolution is a first-class citizen.** Cross-source device
   matching is not a feature of any one module. It lives in `operations`
   and serves all modules equally.

5. **Queue governance by contract.** Every queue inherits health
   monitoring, operational controls, and failure handling by conforming
   to the standard table contract and registering in the queue registry.
   No snowflake queues.

6. **Findings are facts. Rules are responses.** A finding states what is
   wrong and how certain we are. A notification rule decides what to do
   about it. These concerns are strictly separated.

7. **Four-layer storage separation, per-domain top-to-bottom, shared
   reads via effective views.** Every ops entity handles data in four
   layers: canonical (identity + resolver decisions), derived (matview
   refreshed from raw source + config), operator decisions (typed
   per-domain OR polymorphic for simple standalone values), and an
   effective view (`v_<entity>`) that joins the three. Consumers read
   only the effective view. Per-domain storage top-to-bottom; sharing
   only where the output shape is genuinely uniform. See §3.8.

---

## 2. Service and schema naming

### Ingest service

The ingest container is the **Operations Ingest Engine** — one service,
multiple source connectors.

| Layer | Current | Target |
|---|---|---|
| Docker service | `ninja-ingest` | `operations-ingest` |
| DB role | `ninja_ingest` | `operations_ingest` |
| Python package | `ingest/` | unchanged (internal) |

The Docker service rename is trivial (one line in compose). The DB role
rename is a planned migration — recreate role, reassign all grants across
six migrations.

### Schema conventions

| Schema | Role | Source-specific? |
|---|---|---|
| `<source>_core` | Raw staging — mirrors source's native data model | Yes |
| `operations` | Canonical entities, observations, findings, notifications | No |
| `agent_compliance` | Compliance configuration and evaluation (renamed from `ninja_agent_compliance`) | No |

Raw staging schemas (`ninja_core`, `ninja_activities`) are intentionally
source-branded — they reflect that source's native data model. A future
RMM gets its own `<source>_core` schema. Forcing multiple sources into
one staging schema loses fidelity.

`agent_compliance` is a platform feature (multi-source coverage
evaluation), not a Ninja feature. Rename is a planned migration.

---

## 3. Data architecture

### 3.1 Entity types

All observations are classified by `entity_type`. The `platform` field
differentiates sources within a type.

| entity_type | Covers | Platform examples |
|---|---|---|
| `software` | Software installations | Ninja |
| `agent.rmm` | RMM agent presence and check-in | Ninja, ConnectWise |
| `agent.edr` | EDR agent presence | SentinelOne, CrowdStrike |
| `agent.remote_access` | Remote access tool | ScreenConnect, LogMeIn |
| `user` | User accounts (planned) | AD, Azure AD |
| `vulnerability` | CVEs (planned — backlog, NVD enrichment) | SentinelOne, Tenable, NVD |
| `patch` | OS patch state and install outcomes (planned) | Ninja |

### 3.2 Observation pipeline

Every source connector writes to `operations.entity_observations`.
`device_id` is resolved at write time where possible (see §4 Identity
Resolution). Unresolved observations have `device_id = NULL` and are
queued for async resolution.

`ninja_agent_compliance.platform_observations` is the legacy
multi-source observation table. It will be retired once:
1. S1 and ScreenConnect connectors write `agent.*` observations to
   `operations.entity_observations`
2. The compliance evaluator is rebuilt on `operations.*`
3. The compliance engine is validated on the new source

### 3.3 Canonical entities vs. observation-derived tables

| Class | Examples | Auto-delete? |
|---|---|---|
| Canonical entity | `devices`, `clients`, `users` | Never |
| Observation-derived current state | `software_installations_current`, `device_agent_presence_current` | Yes, three-state model |

Canonical entities represent real-world things that existed. Staleness
on a canonical entity triggers a finding — it never triggers deletion.
Deletion is operator-only.

### 3.4 Universal lifecycle columns

Every canonical entity table carries:

```sql
created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
created_reason TEXT        NOT NULL DEFAULT ''
updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
updated_reason TEXT        NOT NULL DEFAULT ''
stale_since    TIMESTAMPTZ
stale_reason   TEXT
deleted_at     TIMESTAMPTZ
deleted_reason TEXT
```

`deleted_at` is set only by explicit operator action. No automated
process ever sets it on a canonical entity.

### 3.5 Reason vocabulary

| Token | When to use |
|---|---|
| `ninja.ingest.full_run` | Upserted during scheduled full-fleet pull |
| `ninja.ingest.scoped_run` | Upserted during scoped (df-filtered) pull |
| `ninja.ingest.activity` | Created/updated from a Ninja activity event |
| `ninja.ingest.new_device` | First time this device_id appeared from Ninja |
| `ninja.ingest.device_disappeared` | Device no longer returned by source API |
| `ninja.ingest.observation_missing` | Entity absent from latest full refresh |
| `operator.dismissed` | Operator explicitly dismissed a finding |
| `operator.deleted` | Operator explicitly deleted a canonical entity |
| `system.migration` | Set during schema migration / seed run |
| `system.reconciliation` | Set during post-ingest reconciliation pass |

### 3.6 Three-state staleness model for `*_current` tables

```
stale_since = NULL      → current (observed in most recent run)
stale_since = <ts>      → stale   (absent from latest run)
deleted_at  = <ts>      → tombstone (stale window expired or operator)
```

Do NOT tombstone rows for devices that are offline. Offline means the
device is not checking in — not that the software was uninstalled.

### 3.7 Offline vs. missing (devices)

| State | Definition | Tracked in |
|---|---|---|
| Offline | Device in API; `is_online = false` | `devices.is_online` |
| Missing | Device no longer returned by API | `device_links.missing_since` |

`device_links` additions needed:
```sql
last_seen_at   TIMESTAMPTZ   -- updated every time device appears in a pull
missing_since  TIMESTAMPTZ   -- set when absent from full pull; cleared on reappearance
```

When `missing_since` is set: create `device_missing_from_source` finding.
When device reappears: clear `missing_since`, auto-resolve finding.

### 3.8 Storage separation — four-layer per-domain design (2026-07-15)

Extends §3.3 by splitting observation-derived state into three distinct
concerns and giving each its own storage. Consumers read one view;
storage semantics stay unambiguous.

**Why this exists:** columns on a canonical entity table used to mix
(1) identity, (2) values recomputed every ingest cycle, (3) permanent
operator decisions, and (4) high-frequency session state. Rule changes
silently invalidated stored values; sync could clobber operator
decisions; readers couldn't tell "current" from "cached." The four
layers give every field one writer and one meaning.

**The four layers per entity:**

1. **Canonical** — `operations.<entity>` (e.g. `operations.devices`).
   Identity, resolver decisions, lifecycle, audit stamps. One writer:
   the resolver. Slow-changing derived attributes MAY stay here when
   they rarely change and share the resolver's writer (e.g. `os_name`,
   `device_role`, `device_type` on `operations.devices` — sync-refreshed
   during identity work, low churn, no dedicated matview needed).
2. **Derived** — per-domain matviews (`operations.<entity>_<domain>_current`
   or aggregate rollups like `device_session_current`). Refreshed from
   raw source + per-domain config. Every matview carries `computed_at`
   so staleness is visible. One writer: the domain's refresh function.
3. **Operator decisions** — either **per-domain typed table**
   (`operations.<entity>_<domain>_override`) when the decision partners
   with a derived value that has domain constraints, OR the
   **polymorphic table** (`operations.<entity>_operator_decisions(
   dimension, value, reason, set_by, set_at)`) when the decision stands
   alone (exemptions, notes, suppress-finding). Never touched by sync.
   One writer: operator via UI.
4. **Effective view** — `operations.v_<entity>`. Joins canonical +
   derived + operator decisions. Exposes `<domain>_derived`,
   `<domain>_override`, and `effective_<domain>_<attr>` (COALESCE of
   override over derived). Consumers read only this — never the
   underlying storage.

**Per-domain top-to-bottom template (per domain `<D>`):**

```
operations.<D>_scope_signal              -- rules (priority-ordered)
operations.<D>_scope_default             -- per-device_role fallback
operations.<D>_scope_policy_allowlist    -- optional domain-specific quirks
operations.device_<D>_scope_current      -- derived matview
operations.device_<D>_override           -- operator override (typed)

operations.refresh_<D>_scope()           -- refresh function
```

`v_device` gains `<D>_scope_derived`, `<D>_scope_reason`,
`<D>_scope_override`, and `effective_<D>_scope`.

**Where sharing is right (uniform output shape, cheap):**

- Effective-view pattern — one `v_<entity>` per entity.
- Polymorphic `<entity>_operator_decisions` — for simple standalone
  decisions with enum / boolean / text values.
- Derived matview shape convention (`computed_at`, `_reason` columns
  when the derivation is non-trivial).

**Where separation is right (input semantics differ, avoid
lowest-common-denominator flattening):**

- Per-domain config tables (rules, defaults, quirks). Input semantics
  differ per domain — patching reads Ninja custom fields with a
  device→org→location cascade; a backup domain would read a different
  source entirely. Forcing a shared "signal" table flattens meaning.
- Per-domain derived matviews with typed columns.
- Per-domain refresh functions.
- Per-domain typed override tables when the override has domain
  constraints (e.g. `device_patching_override.scope CHECK (scope IN
  ('Included','Excluded'))`).

**Refresh coordination:**

Per-domain refresh functions declare their inputs (raw source tables +
config tables). A refresh manifest lists dependency order. Ingest calls
`operations.refresh_derived()` at appropriate points; the manifest
resolves order and refreshes CONCURRENTLY per matview. Each matview
has a unique index so concurrent refresh is possible.

**Tenant scoping on matviews:**

Postgres does NOT support RLS on materialized views (only on tables,
views, and foreign tables). Every derived matview keeps `tenant_id`
on the row, but effective tenant scoping comes through the join to
RLS-enabled canonical tables (e.g. `v_device` joins to
`operations.devices` which has RLS). Consumers reading through the
effective view are safely scoped; a direct SELECT on a matview by a
trusted role (`metabase_ro`, `operations_readonly`) bypasses this and
is an accepted risk for those roles — same pattern as
`device_agent_presence_current` today. Shared operator-decisions tables ARE
regular tables and DO get RLS with the standard policy
(`tenant_id = current_setting('operations.tenant_id', true)::bigint`).

Tightening the matview access boundary via security-barrier view
wrappers is filed in Track O batch O5.

**Adding a new scope domain:**

1. Add row to `operations.scope_dimensions` (registry — listing only,
   not FK-referenced).
2. Create the six per-domain artifacts (three config tables, one
   matview, one override table, one refresh function).
3. Add corresponding LEFT JOINs to `v_device` for the new columns.
4. Consumers read `v_device.effective_<D>_scope`.

Every step is mechanical. No shared-table redesign to accommodate a
new domain.

**Consequence for canonical `operations.devices`:**

- `exemptions` JSONB moves to `device_operator_decisions` (polymorphic,
  standalone decision).
- `lifecycle_status` stays on canonical but is documented as
  operator-preferring: sync only downgrades to `offline_aging`
  automatically; other transitions are operator-only.
- `os_name`, `os_family`, `os_group`, `device_role`, `device_type` stay
  on canonical. Refreshed by the resolver / role sync; rare-change,
  single-writer.
- No session-state columns on canonical (`last_observed_at` /
  `last_contact_at` already live in `device_agent_presence_current`; new
  device-grain rollup lives in `device_session_current`).

**Legacy shapes to reconcile (backlog, non-blocking):**

- `device_agent_presence_current` (per-source matview) — naming predates this
  section; per new convention it would be `device_source_presence_current`.
  Rename filed as follow-up; not blocking.
- `software_decisions` (typed columns) — deliberate exception to the
  polymorphic operator-decisions table. Domain-typed decision with
  specific action structure; keeping typed storage is correct.
  Documented here as the intended exception, not a violation.

---

## 4. Identity resolution

Identity resolution is a **first-class platform function** in
`operations`. It is not owned by any module. Every source connector
benefits from it automatically.

A device seen in Ninja, SentinelOne, and ScreenConnect is one
`operations.devices` row with three `device_links` rows.

### 4.1 Fast-path resolution (inline at ingest)

Runs synchronously at write time. Resolves the simple cases immediately
so `entity_observations.device_id` is set on first write.

| Signal | Confidence | Action |
|---|---|---|
| Same source, `external_id` already in `device_links` | Certain | Resolve immediately |
| Serial number exact match across any source | High | Resolve immediately, log cross-source match |
| Exact hostname, unique match across `device_links` | Medium-high | Resolve immediately, flag as auto-resolved |

Rule: **if you can resolve with certainty at ingest, do it. If you are
guessing, defer.**

**Serial quality.** Serial numbers are only a valid matching signal when
they are real. Placeholder values (`System Serial Number`,
`Default string`, `To Be Filled By O.E.M.`, `0`, `None`, empty) and any
serial shared by more than one device fleet-wide are classified
low-quality and excluded from matching. Quality classification is
computed at ingest and surfaced on the identity review page.

### 4.2 Async resolver (slow path)

Processes observations where `device_id = NULL`. Runs as a processing
queue (see §5). Tries normalized hostname matching and fuzzy signals.
Uncertain matches create an `identity_candidate` for operator review.

### 4.3 Resolution triggers (four writers to resolution queue)

| Trigger | When |
|---|---|
| Ingest fast-path miss | Immediately when inline resolution fails |
| New `device_links` row | Any source adds a new device — re-evaluate existing NULL observations |
| Operator confirms `identity_candidate` | Cascade: resolve all observations that can now be matched |
| Periodic sweep | Every N hours — safety net for anything missed |

### 4.4 Schema additions

```sql
-- operations schema
CREATE TABLE operations.identity_candidates (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id      BIGINT NOT NULL,
    device_id_a    UUID NOT NULL REFERENCES operations.devices(id),
    device_id_b    UUID NOT NULL REFERENCES operations.devices(id),
    confidence     TEXT NOT NULL,   -- 'high' | 'medium' | 'low'
    signals        JSONB NOT NULL,  -- what evidence triggered this
    status         TEXT NOT NULL DEFAULT 'pending',  -- pending | confirmed | rejected
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at    TIMESTAMPTZ,
    resolved_by    TEXT
);
```

---

## 5. Queue system

### 5.1 Two queue types

| Type | Purpose | External dependency |
|---|---|---|
| **Refresh** | Drive API calls to source systems | Yes — rate-limited by source |
| **Processing** | Work on data already in `operations.*` | No — DB only |

Refresh queues need a source client and carry API failure risk.
Processing queues are faster, more reliable, and independent of source
availability.

### 5.2 Queue governance

**Every queue** must conform to all four governance contracts. No
exceptions.

#### Standard table contract

```sql
id           BIGSERIAL    PRIMARY KEY
df           TEXT         NOT NULL,   -- scope or payload
reason       TEXT         NOT NULL DEFAULT '',
queued_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
status       TEXT         NOT NULL DEFAULT 'pending',
attempts     SMALLINT     NOT NULL DEFAULT 0,
max_attempts SMALLINT     NOT NULL DEFAULT 3,
worker_id    TEXT,                    -- reserved for parallelism
started_at   TIMESTAMPTZ,
completed_at TIMESTAMPTZ,
rows_seen    INTEGER,
error        TEXT
```

Unique partial index: `(df) WHERE status = 'pending'` — one pending
entry per scope value per queue.

#### Queue registry

Every queue registers one row in `operations.queue_registry`:

```sql
queue_key          TEXT  -- 'software.scheduled', 'identity.resolution'
queue_type         TEXT  -- 'refresh' | 'processing'
table_name         TEXT  -- 'ninja_core.software_scheduled_queue'
owner              TEXT  -- 'ninja.ingest' | 'operations.resolver'
enabled            BOOL  -- operator toggle (not env var)
max_pending_age_m  INT   -- health threshold: pending entry age
max_failure_count  INT   -- health threshold: failed entry count
max_depth          INT   -- health threshold: pending depth ceiling
description        TEXT
```

Health monitoring, the status UI, and operational controls all read
from the registry. New queue = create table + insert registry row.

One master env var `QUEUE_SUBSYSTEM_ENABLED` gates all queues.
Per-queue enable/disable via `queue_registry.enabled`.

#### Standard worker contract

Every worker implements these five steps in order:

1. `recover_stale()` — reset processing entries past lease window back to pending
2. `claim_batch(n)` — atomically claim N pending entries (FOR UPDATE SKIP LOCKED)
3. `process(entry)` — do the work
4. `complete(entry_id)` — mark done, record result
5. `fail(entry_id)` — increment attempts; retry if below max, else fail permanently

Refresh queues add: acquire source client before step 3.

Lease window: 30 minutes. Demand queue stale entries → fail (no worker
to re-pick them up); background queue stale entries → reset to pending.

#### Health contract

The health evaluator runs periodically and checks each registered queue:
- Oldest pending entry age vs. `max_pending_age_m`
- Failed entry count vs. `max_failure_count`
- Pending depth vs. `max_depth`

Breach → `operations.admin_findings` row opens automatically.
Recovery → finding auto-resolves.
No per-queue monitoring code required.

### 5.3 Queue catalogue

**Refresh queues**

| Queue | Trigger(s) | Scope | Status |
|---|---|---|---|
| `software_scheduled_queue` | Schedule (every N hours) | Per org | Built |
| `software_demand_queue` | Operator via HTTP form | Org or device | Built |
| `software_activity_queue` | SOFTWARE_* activity event | Per device | Built |
| `agent_presence_scheduled_queue` | Schedule | Per org, per source | Planned |
| `agent_presence_demand_queue` | Operator | Org or device | Planned |
| `agent_presence_activity_queue` | Agent install/uninstall event | Per device | Planned |
| `device_verify_queue` | `missing_since` set on device_links | Per device | Planned |

**Processing queues**

| Queue | Trigger(s) | Scope | Status |
|---|---|---|---|
| `identity_resolution_queue` | Fast-path miss / new device_links / operator confirm / sweep | Per observation | Designed |
| `compliance_evaluation_queue` | Observation state change / rule change | Per device | Planned |
| `finding_lifecycle_queue` | Entity state change (stale, missing, recovered) | Per entity | Planned |
| `notification_dispatch_queue` | Finding opens / escalates | Per finding | Planned |

**Plug & play checklist for a new queue:**
1. Create table matching standard contract
2. Insert into `operations.queue_registry`
3. Implement worker following five-step contract
4. Register worker with scheduler

Health monitoring, operational toggles, admin findings — all inherited.

---

## 6. Findings system

### 6.1 Two finding classes

| | Entity findings | Admin findings |
|---|---|---|
| About | A device, client, or user | The Operations platform itself |
| Audience | MSP operators | System admins |
| Closes when | Entity state recovers | System state recovers |
| Lives in | `operations.findings` | `operations.admin_findings` |
| Surfaces in | Device / client pages | System health page |
| Auto-resolves | Yes, when condition clears | Yes, when condition clears |

**The Health system IS admin findings.** No separate subsystem.
The admin findings page in Operations IS the Health dashboard.

### 6.2 Finding types registry

Every finding type registers in `operations.finding_types`:

```sql
type_key               TEXT  -- 'missing_required_platform', 'software_queue_stalled'
finding_class          TEXT  -- 'entity' | 'admin'
source_module          TEXT  -- 'agent_compliance' | 'queue_health' | 'identity_resolver'
default_severity       TEXT  -- 'critical' | 'high' | 'medium' | 'low' | 'info'
auto_resolvable        BOOL
description            TEXT
```

New finding type = one row here. The notification engine, review page,
and correlation rules discover it automatically.

### 6.3 Coverage requirements

Coverage requirements are **declarative policy** — what should exist for
a given entity/org/device scope. They are the input to the platform
evaluator. Modules define them; the platform evaluates against them.

```sql
-- operations schema
CREATE TABLE operations.coverage_requirements (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           BIGINT NOT NULL,
    client_id           UUID,                  -- NULL = applies to all clients
    entity_type         TEXT NOT NULL,         -- 'agent.edr', 'agent.rmm', ...
    platform            TEXT,                  -- NULL = any platform of this type
    device_scope        TEXT NOT NULL,         -- 'all' | 'servers' | 'workstations'
    severity            TEXT NOT NULL,         -- finding severity when gap detected
    gap_after_hours     INT  NOT NULL,         -- hours before gap is flagged
    confidence_probable INT  NOT NULL,         -- hours → confidence becomes probable
    confidence_confirmed INT NOT NULL,         -- hours → confidence becomes confirmed
    enabled             BOOL NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

This replaces `ninja_agent_compliance` alert_rules as the source of
compliance policy. Agent compliance becomes a configuration domain only.

### 6.4 Platform evaluator

The platform evaluator is a **generic, domain-agnostic** gap analysis
engine. It does not know about Ninja, SentinelOne, or ScreenConnect
specifically.

Logic: for each device in scope, for each coverage requirement that
applies, does a current observation of the required entity_type exist?
If not, open or update a finding.

**Triggered by (both — hybrid model, same pattern as queues):**
- Event-driven: new observation arrives → evaluate that device immediately
- Scheduled sweep: periodic backstop covering any gaps missed by events

**Evaluation universe is observation-driven, not Ninja-driven.** A
device known only to SentinelOne or ScreenConnect is still a canonical
device — the async resolver promotes stable unmatched observation
clusters into `operations.devices` (+ `device_links`) so the evaluator
sees them. "Has ScreenConnect but no RMM agent" must produce a finding;
an evaluator that only iterates Ninja-sourced devices cannot detect it.

**Device scope applies.** Requirements carry `device_scope`
(all/servers/workstations); the evaluator filters on
`devices.device_type`, which every connector populates (Ninja
node_class, else OS-name inference).

**Exemptions apply.** A device flagged exempt for an entity_type (e.g.
Ninja "NO AV" → `agent.edr`) is skipped for requirements of that type.
Exemption flags are carried on the device (set from source data at
ingest), not hard-coded per platform.

**Source-failure guard.** When a source's latest collection run failed
or is overdue, the evaluator (a) opens a `source_failure` **admin**
finding for that source and (b) skips gap evaluation for that platform
until a successful run lands. A broken S1 pull must never open
fleet-wide false "missing EDR" findings. This replaces the legacy
per-device "unknown" state with the entity/admin split of §6.1.

### 6.5 Confidence, severity, and urgency

These are three distinct dimensions, each with a single definition point:

**Confidence** — how certain we are the gap is real. Computed by the
evaluator from thresholds defined on the coverage requirement.
Evolves over time.

```
possible   → gap_after_hours threshold crossed
probable   → confidence_probable threshold crossed
confirmed  → confidence_confirmed threshold crossed AND corroborated
```

**Corroboration:** a gap is only `confirmed` when the device is
demonstrably alive — observed online by at least one other platform
within the staleness window (or an operator confirmed it manually). A
device that is dark everywhere is probably retired; its gaps stay
`probable`. This is the legacy `confirmed_gap` rule and is the primary
false-positive control — notification rules typically filter on
`min_confidence = confirmed`.

**Severity** — how bad this finding is. Defined on the coverage
requirement at creation time. **Immutable after the finding opens.**
Industry standard: severity is a static impact measure, not a
time-varying signal.

The `finding_types` registry holds default severity. The coverage
requirement overrides it for specific scopes (e.g., missing EDR on
servers = critical, not just high).

**Urgency** — time pressure for re-escalation. Defined on notification
rules. Drives re-notification on acknowledged findings if unresolved
past the urgency window. Independent of severity.

Notification rules filter on all three independently.

### 6.6 Finding deduplication

Two independent dedup mechanisms:

**Finding dedup** — prevents duplicate open findings for the same
condition. Each finding carries a `condition_key` (deterministic hash of
`tenant_id + client_id + device_id + finding_type`). Unique constraint
on `(condition_key)` where `status = 'open'`.

**Notification dedup** — prevents duplicate alerts for the same finding.
Fingerprint + cooldown window in `operations.notification_state`. The
`condition_key` is the dedup fingerprint.

These are orthogonal. Dedup is stateless signal clustering. Ack is
response lifecycle. Ack does not affect dedup logic.

### 6.7 Finding lifecycle

```
open → acknowledged → resolved
         ↑                ↑
   human claims it   condition clears
                     (auto or operator)
```

- **open**: condition detected, no response yet
- **acknowledged**: operator has claimed it; escalation notifications
  suppressed; re-escalation fires anyway after urgency timeout
- **resolved**: condition cleared (auto when evaluator sees it gone, or
  operator closes explicitly)

`last_detected_at` is refreshed on every evaluation cycle while the
condition persists. This drives staleness detection on acknowledged
findings.

### 6.8 Suppression

Explicit operator rule: suppress this finding type for this
device/client for N days. Time-bounded. After expiry, finding reopens
normally if condition still exists.

Lives in `operations.finding_suppressions` — platform-level, applies
across all finding types, not per module.

---

## 7. Notification system

### 7.1 Architecture

```
operations.findings / operations.admin_findings
              ↓
operations.notification_rules    platform-owned, reference finding_type
              ↓
operations.notification_routes   delivery channels
              ↓
operations.notification_state    dedup + cooldown per fingerprint
operations.notification_events   full delivery audit trail
```

Modules do not own notification rules. Notification rules are a platform
concern defined per finding_type, not per module.

### 7.2 Notification rules

```sql
operations.notification_rules
  rule_id          UUID PRIMARY KEY
  tenant_id        BIGINT NOT NULL
  finding_type     TEXT NOT NULL     -- references finding_types.type_key
  finding_class    TEXT NOT NULL     -- 'entity' | 'admin'
  min_severity     TEXT              -- 'critical' | 'high' | 'medium' | ...
  min_confidence   TEXT              -- 'confirmed' | 'probable'
  client_id        UUID              -- NULL = all clients
  match_criteria   JSONB             -- domain-specific extra dimensions
  route_id         UUID NOT NULL REFERENCES notification_routes
  urgency_hours    INT               -- re-escalate acked finding after N hours
  cooldown_hours   INT NOT NULL DEFAULT 24
  enabled          BOOL NOT NULL DEFAULT true
```

`match_criteria` JSONB handles domain-specific dimensions without
polluting the base schema. Agent compliance adds `device_scope`,
`affected_platform` there.

### 7.3 Routes, state, events

Moved from `ninja_agent_compliance` to `operations`:

```
operations.notification_routes   channels: webhook, email, Zendesk
operations.notification_state    dedup/cooldown per fingerprint
operations.notification_events   delivery audit trail (all domains)
```

`target_ref` on routes points to an env var name — credentials stay
outside the DB.

### 7.4 Channels

- **Webhook** — HTTP POST, configurable URL via env var
- **Email** — SMTP, configurable host/port/TLS/auth
- **Zendesk** — API v2, requester/subject/comment

### 7.5 Findings review page

The **findings review page** in the Operations web app shows all
unresolved findings, filterable by:
- Client / org
- Finding type
- Finding class (entity / admin)
- Severity
- Confidence
- Status (open / acknowledged)

This is the operational triage surface. The existing AC `review_digest`
Metabase dashboard serves a separate analytical/reporting purpose and
remains in place — different use case, different audience.

---

## 8. Agent compliance migration path

Current state: `ninja_agent_compliance` is a multi-source compliance
engine bundling data collection, identity resolution, evaluation, finding
generation, and alert routing in one module.

Future state: **deleted entirely.** No stripped-down remnant, no
configuration residue. The end state is:

- `rg "agent_compliance|ninja_agent_compliance"` returns zero hits in
  `ingest/` and `operations/` (excluding migration history);
- the `ninja_agent_compliance` schema is dropped;
- `ingest/agent_compliance/` is removed from the tree;
- no new code may import `ingest.agent_compliance.*` or query
  `ninja_agent_compliance.*` — such a dependency blocks cutover.

Source configuration (URLs, credential env-var refs, shared/per-client
scoping) lives in `operations.sources` / `source_instances` /
`source_bindings`. Connector fetchers live in `ingest/connectors/`.
Hostname/org normalization lives in a platform-neutral module.
Client-to-source-group mapping lives in `operations.client_links`.

| Responsibility | Current home | Future home |
|---|---|---|
| S1 / SC data collection | `ninja_agent_compliance` ingest | Source connectors → `entity_observations` |
| Identity resolution | `ninja_agent_compliance` norm_name / merge_candidates | `operations` identity resolver |
| Coverage requirements | `ninja_agent_compliance` alert_rules | `operations.coverage_requirements` |
| Compliance evaluation | `ninja_agent_compliance` evaluate() | Platform evaluator |
| Finding generation | `ninja_agent_compliance` evaluate() | Platform evaluator → `operations.findings` |
| Alert routing | `ninja_agent_compliance` alerts.py | `operations` notification engine |
| Review digest (analytical) | Metabase dashboard | Stays in Metabase |
| Notification rules | `ninja_agent_compliance.alert_rules` | `operations.notification_rules` |
| Routes / state / events | `ninja_agent_compliance.*` | `operations.*` |
| Suppressions | `ninja_agent_compliance.alert_suppressions` | `operations.finding_suppressions` |
| Schema rename | `ninja_agent_compliance` | `agent_compliance` |

The `agent_compliance` schema rename (backlog item 25) is superseded:
there is nothing left to rename once the module is deleted.

---

## 9. Parity tracks (2026-07-09)

The original 25-item gap backlog is complete through the platform
foundation (items 1–19, 21–23 shipped in v0.36–0.43). Remaining work is
organized as parity tracks in `BLUEPRINT.md` — the goal is full
functional parity with the legacy AC engine, the standalone compliance
scripts, and the Metabase operational dashboards, followed by deletion
of `ninja_agent_compliance` (§8).

| Track | Content |
|---|---|
| 0 | Legacy severance — connectors, source config, client resolution move off `ninja_agent_compliance` |
| 1 | Evaluator parity — observation-driven universe, device_scope, exemptions, stale/source-failure/cross-client findings, corroborated confidence |
| 2 | Notification dispatcher — rules→routes→state→events, suppressions with ignore/restore, webhook/email/Zendesk, review digest |
| 3 | Software findings — classification pipeline for the seeded software finding types, catalog decision workflow (3b CVE/NVD enrichment: backlog) |
| 4 | Identity fidelity — normalization/prefix/macOS matching, serial quality, candidate confirm/reject with cascade, conflict views |
| 5 | Patching platform layer — patch findings + work queue over `ninja_patches` staging (§10) |
| 6 | Cutover — side-by-side validation, Metabase disposition (§12), delete legacy |
| U | UI framework — nav, page grammar, canonical entity pages (§11); surfaces land per-track as engines produce data |

Backlog (not committed): 3b CVE/NVD enrichment (`vulnerability` entity
type), VirusTotal/reputation lookups, user-risk scoring (needs a
last-user data source), DB role rename `ninja_ingest` →
`operations_ingest`.

---

## 10. Patching platform layer

`ninja_patches` is a legitimate source-branded staging schema (§2) and
stays. What is missing is the platform layer on top: findings and
operator workflow. The Metabase patch dashboards prove the operational
intent — triage, not charts.

**Patch finding types (entity class):**

| type_key | Condition | Default severity |
|---|---|---|
| `device_never_patched` | Device in patching scope, no patch scan/install history | high |
| `patching_stalled` | No patch activity for N days (default 35) on an otherwise-active device | high |
| `reboot_pending` | Installed patches awaiting reboot beyond N days | medium |
| `patch_failing_repeatedly` | Same KB failed ≥3 consecutive attempts on a device | high |
| `patch_approval_backlog` | Manual-approval queue for a client exceeds threshold/age | medium (subject: client) |

The evaluator reads `ninja_patches.current_patch_state`,
`latest_install_outcome`, and `device_patch_signal` (already
materialized) — no new collection needed. Findings flow through the
standard pipeline: review page, notification rules, suppressions.

**Operator surfaces:** patch work queue (triage list mirroring the
"Device Work Queue" dashboard intent), client patch review, patch tab
on the canonical device page. Trend/evidence analytics stay in
Metabase.

A `patch` entity_type in `entity_observations` is **not** required for
this layer; it becomes relevant only if a second patching source ever
appears.

---

## 11. Operator UI

Operations is the operational data browser and control plane (product
direction, 2026-07-07). Metabase keeps exploratory BI and historical
analytics. The dividing line: **if a page carries a decision or an
action, it belongs in Operations.**

### 11.1 Information architecture (revised 2026-07-16)

Operator-facing nav — 5 primary domains + fleet-wide search on
the right, admin cluster grouped into 3 collapsed pages:

```
Dashboard · Clients · Patching · Software · Issues    [🔍 search]    Review · Config · System · ⚙
```

- **Dashboard** — client-portfolio-first scoreboard. Alerts +
  overview cards + attention panel + client grid + sidebar. See
  §11.5 principles.
- **Clients** — fleet-wide client list; enter client context
  from here.
- **Patching** — per-domain triage: 5 finding types, scope
  layer, population summary, device drilldown.
- **Software** — per-domain ecosystem view: inventory,
  categorization, decisions, issues (as a facet).
- **Issues** — cross-domain triage queue (previously "Findings").
  Everything actionable, filterable by category, severity, client,
  online state.

Client context sub-nav (when inside a client):
```
<Client> · Devices · Patching · Software · Policies
```

Admin cluster (right-aligned):
- **Review** — Client candidates + Identity matches + Merge
  candidates. Sum badge.
- **Config** — Notification rules + Requirement profiles +
  Software catalog + Patching-scope rules.
- **System** — Sources + Ingest health + Queue status.
- **⚙** — Django admin.

### 11.2 Page grammar

Every list page follows one shape: summary tiles → filter bar →
paginated table → row links to a canonical detail page → actions live
on the detail page. Shared template components (tiles, filter bar,
table, pagination, severity/status/confidence badges, freshness
header) are defined once and reused — no per-page CSS or bespoke table
markup.

Every domain page shows **data freshness** (last successful ingest run
for the backing source, from `run_log`) in the header.

### 11.3 Canonical entity pages

One page per entity; everything else links to it:

- **Device** — identity (links per source, serial quality), agent
  presence per platform, software, patches, open findings, history.
- **Client** — coverage summary, devices, software rollup, patch
  posture, findings, source links.
- **Finding** — full detail, evidence, ack/suppress/resolve actions,
  notification history.
- **Source** — binding status, last runs, per-client link table.

### 11.4 Standing workflows

| Workflow | Surfaces | Actions |
|---|---|---|
| **Triage** | Findings queue (entity), Health (admin) | acknowledge, suppress (time-bound, with restore), resolve |
| **Review** | Identity candidates, software decisions, unmatched source groups | confirm/reject, approve/approve-publisher/reject/investigate |
| **Configure** | Coverage requirements, notification rules + routes, suppressions, sources | CRUD with audit |

**Engine-first rule:** no surface ships before its backing engine
produces real data. A page rendering an empty table is a defect, not a
milestone.

### 11.5 Standing UI principles (2026-07-16)

Distilled from the operator feedback captured in the UI redesign
(Track UI-2). These are hard rules — every new page adheres.

1. **Entity-first, not issue-first.** Every domain (Clients,
   Devices, Software, Users, …) gets a page presenting the whole
   ecosystem. Issues are ONE facet of that domain, not the
   framing. The Dashboard is a client-portfolio scoreboard, not
   an alerts inbox.
2. **Portfolio-first Dashboard.** MSP / fleet operator lands
   on a client-portfolio view. Overview cards + attention panel
   + client grid + sidebar. Domain deep-dives happen via nav,
   not via hero tiles.
3. **Human-friendly copy.** No internal identifiers in visible
   copy. Central `humanize_label` template filter translates
   snake_case DB values to plain English. Banned words: **"findings"**
   (use "issues" / "items"), **"fleet"** (use "devices" / "across
   all clients"). British spellings banned — US English only.
4. **Admin separate from operator.** Left nav = daily workflow
   domains. Right-muted = configuration + platform health +
   review queues.
5. **Summary top, details below.** Every domain page: alerts →
   overview cards → attention panel → primary grid → sidebar.
6. **Every table sortable + filterable.** Column headers sort;
   filter bar above; searchable + multi-select where meaningful.
7. **Missing ≠ Stale.** Different problems, different actions,
   different labels. Missing = actionable coverage gap; Stale
   = mixed bag, may include offline devices where nothing can
   be done. Never conflate.
8. **Signal over noise.** Panels like "Needs immediate attention"
   restrict to severe (critical + high) severity and hide when
   empty. Aggregate counts across domains only when the sum is
   itself actionable.
9. **Action-per-pixel.** Every card / row / badge either
   clickthroughs to a filtered view, offers an inline action,
   or provides context. No decoration.
10. **Native components only.** No third-party JS libraries.
    Native HTML `<select>`, `<input type="search">`, existing
    sort JS. Adds complexity + fragility (Tom Select incident
    2026-07-16 — reverted).

Full principles + WHY each exists is in
`~/.claude/projects/.../memory/feedback_ui_principles.md`.

---

## 12. Metabase disposition at cutover

The AC Metabase dashboards query `ninja_agent_compliance.v_*` views and
break when the schema drops. Disposition is explicit, per dashboard:

| Class | Disposition |
|---|---|
| Workflow/triage cards (Today, Devices, Alerts, Customers, Setup, Debug) | Superseded by Operations pages — delete |
| Health cards (source health, sync lag) | Superseded by Health page — delete |
| Trend/analytics cards worth keeping | Rebuild on `operations.*` views |
| Patching dashboards | Unaffected (read `ninja_patches`, which stays); triage-intent cards gradually superseded by Track 5 surfaces |
| Inventory dashboards (`ninja_inventory`) | Identity/serial cards superseded by Track 4 surfaces; rest reviewed at cutover |

No dashboard is dropped implicitly. Track 6 includes the inventory of
which cards get rebuilt vs. deleted, approved before the schema drop.
