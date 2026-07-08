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
| `vulnerability` | CVEs (planned) | SentinelOne, Tenable |

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
| Observation-derived current state | `software_installations_current`, `agent_presence_current` | Yes, three-state model |

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

### 6.5 Confidence, severity, and urgency

These are three distinct dimensions, each with a single definition point:

**Confidence** — how certain we are the gap is real. Computed by the
evaluator from thresholds defined on the coverage requirement.
Evolves over time.

```
probable   → gap_after_hours threshold crossed, device online
confirmed  → confidence_confirmed threshold crossed
```

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

Future state: stripped to configuration only.

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

After migration, `agent_compliance` holds only:
- `coverage_requirements` (or these move to `operations`)
- Any AC-specific configuration that has no generic equivalent

---

## 9. Planned gap backlog

In priority order:

| # | Gap | Where |
|---|---|---|
| 1 | `INGEST_ACTIVITY_TYPES_INCLUDE` add SOFTWARE_* | Server `.env` on am-ch-01 |
| 2 | `stale_since/reason`, `deleted_at/reason` on `software_installations_current` | SQL migration |
| 3 | Update `refresh_software_installations_current()` to three-state logic | DB function |
| 4 | `device_links.last_seen_at`, `device_links.missing_since` | SQL migration |
| 5 | Universal lifecycle columns on `devices` + `clients` | Django migration |
| 6 | Entity finding types: `device_missing_from_source`, `device_long_offline`, `device_stale_data` | Seed migration |
| 7 | Post-upsert reconciliation in `devices.py` | Ingest code |
| 8 | `operations.finding_types` registry table | Django migration |
| 9 | `operations.coverage_requirements` table | Django migration |
| 10 | `operations.admin_findings` table + Django model | Django migration |
| 11 | `operations.queue_registry` table + Django model | Django migration |
| 12 | `operations.identity_candidates` table | Django migration |
| 13 | `operations.notification_routes/rules/state/events` (move from AC) | Django migration |
| 14 | `operations.finding_suppressions` table | Django migration |
| 15 | Platform evaluator (generic gap analysis engine) | Ingest code |
| 16 | Identity resolver (async worker + fast-path helper) | Ingest code |
| 17 | S1 connector → `entity_observations` (agent.edr) | Ingest code |
| 18 | ScreenConnect connector → `entity_observations` (agent.remote_access) | Ingest code |
| 19 | `agent_presence_current` materialized view | SQL migration |
| 20 | Compliance engine rebuilt on `operations.*` | Ingest code |
| 21 | Findings review page in Operations web app | Django views + templates |
| 22 | System health page (admin findings) in Operations web app | Django views + templates |
| 23 | Docker service rename `ninja-ingest` → `operations-ingest` | docker-compose.yml |
| 24 | DB role rename `ninja_ingest` → `operations_ingest` | Migration across 6 files |
| 25 | Schema rename `ninja_agent_compliance` → `agent_compliance` | SQL migration |

Items 1–3: blocking for correct software staleness.
Items 4–7: blocking for correct device lifecycle.
Items 8–16: platform foundation — evaluator, identity resolver, findings tables.
Items 17–22: AC migration (depends on 8–16).
Items 23–25: naming cleanup (can be done independently at any time).
