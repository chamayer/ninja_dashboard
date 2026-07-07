# Entity Lifecycle Design

Architectural decisions for how entities are created, tracked, and retired
across Operations. Applies to canonical entities (devices, clients, users)
and observation-derived current-state tables (software_installations_current,
and any future *_current tables).

---

## 1. Canonical entities vs. observation-derived tables

Two fundamentally different classes of data:

| Class | Examples | Auto-delete allowed? |
|---|---|---|
| **Canonical entity** | `devices`, `clients`, `users` | **Never** |
| **Observation-derived current state** | `software_installations_current` | Yes, via three-state model |

Canonical entities represent real-world things that existed. Deleting them
destroys audit history and breaks FK relationships. Staleness on a canonical
entity is a **finding to investigate**, not a trigger for deletion.

Observation-derived `*_current` tables are ephemeral materialized views of
the latest observed state. They are refreshed from `entity_observations` and
can be soft-deleted when an observation disappears.

---

## 2. Universal lifecycle columns

Every canonical entity table carries these eight columns:

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

Rules:
- `created_reason` / `updated_reason`: always set on write. Use the vocabulary below.
- `stale_since` / `stale_reason`: set by automated reconciliation when a
  canonical entity can no longer be confirmed current. Triggers a finding;
  does NOT delete the row.
- `deleted_at` / `deleted_reason`: set **only by explicit operator action**.
  No automated process ever sets `deleted_at` on a canonical entity.

---

## 3. Reason vocabulary

Standard values for `*_reason` columns. Use these literals so queries and
runbooks can filter consistently:

| Token | When to use |
|---|---|
| `ninja.ingest.full_run` | Upserted during a scheduled full-fleet pull |
| `ninja.ingest.scoped_run` | Upserted during a scoped (df-filtered) pull |
| `ninja.ingest.activity` | Created/updated in response to a Ninja activity event |
| `ninja.ingest.new_device` | First time this device_id appeared from Ninja |
| `ninja.ingest.device_disappeared` | Device no longer returned by source API |
| `ninja.ingest.device_offline` | Device present in API but not checking in |
| `ninja.ingest.observation_missing` | Software row absent from latest full refresh |
| `operator.dismissed` | Operator explicitly dismissed a finding |
| `operator.deleted` | Operator explicitly deleted a canonical entity |
| `operator.merged` | Two records merged by operator action |
| `system.migration` | Set during a schema migration / seed run |
| `system.reconciliation` | Set during a post-ingest reconciliation pass |

---

## 4. Three-state model for observation-derived `*_current` tables

Applies to `software_installations_current` and any future `*_current` table.

```
NULL stale_since          → current (observed in most recent run)
stale_since = <ts>        → stale   (was current; not seen in latest run)
deleted_at  = <ts>        → tombstone (stale window expired or operator action)
```

Staleness window: 48 hours (configurable). Do NOT tombstone rows from
devices that are offline — offline means "device not checking in", not
"software uninstalled". A row on an offline device should remain current
until the device comes back and is re-observed.

Required columns on every `*_current` table:

```sql
stale_since   TIMESTAMPTZ
stale_reason  TEXT
deleted_at    TIMESTAMPTZ
deleted_reason TEXT
```

`refresh_software_installations_current()` must implement:
1. INSERT new observations (already done).
2. UPDATE stale_since = now() where row not in current batch AND device is online.
3. DELETE (tombstone) rows where stale_since < now() - interval '48 hours'.
4. Skip step 2 for rows belonging to offline devices (`devices.is_online = false`).

---

## 5. Offline vs. missing distinction (devices)

Two different states that look similar but have different operational meaning:

| State | Definition | Where tracked |
|---|---|---|
| **Offline** | Device visible in Ninja API; `is_online = false` | `devices.is_online` (already exists) |
| **Missing** | Device no longer returned by Ninja API at all | `device_links.missing_since` (to be added) |

Additions required to `device_links`:

```sql
last_seen_at   TIMESTAMPTZ   -- updated every time this device appears in a Ninja pull
missing_since  TIMESTAMPTZ   -- set when device absent from full pull; cleared on re-appearance
```

Post-upsert reconciliation in `devices.py` (to be added):

After each full-fleet device pull, run a pass that sets
`missing_since = now()` on any `device_links` row whose `external_id` was
NOT present in the current pull (i.e., device has vanished from the API).

When `missing_since` is set:
- Create a finding of type `device_missing_from_source`.
- Do NOT set `devices.deleted_at` — that is operator-only.

When the device reappears:
- Clear `missing_since = NULL`.
- Resolve/close the `device_missing_from_source` finding automatically.

---

## 6. Finding types to be seeded

New finding types needed to support the lifecycle model:

| type_key | severity | title |
|---|---|---|
| `device_missing_from_source` | warning | Device missing from source |
| `device_long_offline` | info | Device offline for extended period |
| `device_stale_data` | info | Device data not refreshed recently |

`device_missing_from_source` is the primary signal for "admin deleted this
from Ninja" — differentiated from `device_long_offline` which fires when
the device is still in Ninja but `is_online = false` for N days.

---

## 7. Software queue architecture (event-driven refresh)

Full fleet pulls via `/queries/software` cover ~472k rows fleet-wide. Three
separate queues handle different execution priorities. The direct full-fleet
pull (`run_software_once`) is removed — coverage is maintained entirely
through the queue system.

### Three queues

| Queue | Table | Source | Execution | df granularity |
|---|---|---|---|---|
| 1 – Scheduled sweep | `ninja_core.software_scheduled_queue` | `enqueue_all_orgs()` on timer | Background worker, polled | `org=<ninja_org_id>` |
| 2 – On-demand | `ninja_core.software_demand_queue` | Operator via HTTP form | **Immediate thread on enqueue** | `org=X` or `id=X` |
| 3 – Activity | `ninja_core.software_activity_queue` | Activity processor on SOFTWARE_* | Same background worker as Q1 | `id=<ninja_device_id>` |

Queues 1 and 3 share one background worker. The worker drains Q3 (activity)
entries before Q1 (scheduled) entries within each tick. Queue 2 never waits
for the worker — it fires a thread the moment the operator submits.

### Queue schemas (ninja_core)

All three tables share the same column shape:

```sql
CREATE TABLE ninja_core.software_<name>_queue (
    id           BIGSERIAL    PRIMARY KEY,
    df           TEXT         NOT NULL,
    reason       TEXT         NOT NULL DEFAULT '',
    queued_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    status       TEXT         NOT NULL DEFAULT 'pending',
    attempts     SMALLINT     NOT NULL DEFAULT 0,
    max_attempts SMALLINT     NOT NULL DEFAULT 3,
    worker_id    TEXT,                          -- reserved for future parallelism
    started_at   TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    rows_seen    INTEGER,
    error        TEXT
);

-- Deduplication: one pending entry per df value per queue
CREATE UNIQUE INDEX ON ninja_core.software_<name>_queue (df)
    WHERE status = 'pending';
```

### Failure handling

**Stuck entries (lease expiry):** On each worker tick, before claiming new
work, reset any `processing` entry where `started_at < now() - interval '30 minutes'`
back to `pending`. Handles container restarts mid-run.

**Repeated failures (retry cap):** On failure, increment `attempts`. If
`attempts < max_attempts`, reset to `pending`. If `attempts >= max_attempts`,
leave as `failed` permanently. Operator can re-enqueue manually.

**Full API outage:** All entries exhaust their retries and land in `failed`.
The next scheduled `enqueue_all_orgs()` tick repopulates Q1. Q3 entries
from missed activities are lost — acceptable because the scheduled sweep
restores coverage within `SOFTWARE_INGEST_SCHEDULE_HOURS`.

### On-demand status page

Queue 2 is for operators who are actively waiting for results. The HTTP flow:

1. `GET /run/software/enqueue` → form (df input, org or device)
2. `POST /run/software/enqueue` → writes demand entry, fires thread, redirects
   to `/run/software/demand/<id>`
3. `GET /run/software/demand/<id>` → status page, auto-refreshes every 5s
   until `status` is `done` or `failed`
4. Status page shows: `df`, `status`, `started_at`, `completed_at`,
   `rows_seen`, `error`

### Queue writers

| Writer | Where | Enqueues to |
|---|---|---|
| `enqueue_all_orgs()` | `main.py`, scheduler | Q1 — one row per `ninja_core.organizations.id` |
| HTTP form submit | `main.py`, `_handle_software_enqueue()` | Q2 — fires thread immediately |
| Activity processor | `activities/ingest.py`, SOFTWARE_* handler | Q3 — df=id=<ninja_device_id> |
| New device detection | `devices.py`, first-seen path | Q3 — df=id=<ninja_device_id> |

### Config knobs

```
SOFTWARE_QUEUE_ENABLED=false          # gates both worker and enqueue_all_orgs
SOFTWARE_INGEST_SCHEDULE_HOURS=24     # how often enqueue_all_orgs fires
SOFTWARE_QUEUE_POLL_MINUTES=5         # how often the Q1/Q3 worker ticks
SOFTWARE_QUEUE_WORKER_BATCH=3         # entries per worker tick
```

`SOFTWARE_QUEUE_ENABLED=false` (default): writers still insert rows so the
queue accumulates; worker is a no-op. Lets the tables be populated before
the worker is turned on.

### Prerequisite

`INGEST_ACTIVITY_TYPES_INCLUDE` in the server `.env` must include
`SOFTWARE_ADDED,SOFTWARE_REMOVED,SOFTWARE_UPDATED`. Currently absent — the
activity processor never sees these. Must be added before Q3 writers fire.

---

## 8. Admin findings

Admin findings are platform-level signals about the Operations system itself
— not about any managed device or client. They are source-agnostic: a queue
failure from the Ninja ingest and a future failure from another source both
land in the same place.

### Separation from entity findings

| | Entity findings | Admin findings |
|---|---|---|
| About | A device, client, or user | The Operations platform itself |
| Audience | MSP operators | System admins |
| Closes when | Entity state recovers | System state recovers |
| Lives in | `operations.findings` | `operations.admin_findings` |
| Surfaces in | Device / client pages | System health page (Operations web app) |

Admin findings are **not** in `ninja_core` — they belong to Operations
because they are independent of which source caused them.

### Table (operations schema, Django-managed)

```sql
CREATE TABLE operations.admin_findings (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    BIGINT       NOT NULL REFERENCES operations.tenants(id),
    type_key     TEXT         NOT NULL,   -- e.g. 'software_queue_drain_stalled'
    severity     TEXT         NOT NULL,   -- 'info' | 'warning' | 'critical'
    title        TEXT         NOT NULL,
    detail       JSONB        NOT NULL DEFAULT '{}',
    source       TEXT         NOT NULL,   -- e.g. 'ninja.ingest'
    opened_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    resolved_at  TIMESTAMPTZ,
    resolve_reason TEXT
);
```

### Finding types for queue health

| type_key | severity | Condition |
|---|---|---|
| `software_queue_drain_stalled` | warning | Q1/Q3 depth not decreasing over 3 consecutive ticks |
| `software_queue_high_failures` | warning | Failed entries exceed threshold (default: 10) |
| `ninja_api_degraded` | critical | Consecutive Ninja API errors across multiple queue runs |

These open and auto-resolve based on system state. The ingest container
writes to `operations.admin_findings` using the `ninja_ingest` role, which
will need INSERT + UPDATE grants on this table.

---

## 9. Current gaps (work to be scheduled)

In priority order:

| # | Gap | Where |
|---|---|---|
| 1 | `INGEST_ACTIVITY_TYPES_INCLUDE` missing SOFTWARE_* types | Server `.env` on am-ch-01 |
| 2 | `stale_since/reason`, `deleted_at/reason` on `software_installations_current` | SQL migration |
| 3 | Update `refresh_software_installations_current()` to three-state logic | DB function |
| 4 | `device_links.last_seen_at`, `device_links.missing_since` | SQL migration |
| 5 | Universal lifecycle columns on `devices` + `clients` | Django migration |
| 6 | Entity finding types: `device_missing_from_source`, `device_long_offline`, `device_stale_data` | Seed migration |
| 7 | Post-upsert reconciliation in `devices.py` | ingest code |
| 8 | Remove `run_software_once()` from `main.py` + scheduler + catch-up | ingest code |
| 9 | `operations.admin_findings` table + Django model | Django migration |
| 10 | `ninja_core.software_scheduled_queue` + `demand_queue` + `activity_queue` tables | SQL migration |
| 11 | Queue writers: activity processor + new device detection + `enqueue_all_orgs()` | ingest code |
| 12 | Q1/Q3 background worker + on-demand status page + config knobs | ingest code |
| 13 | System health page in Operations web app | Django views + templates |

Items 1–3: blocking for correct software staleness.
Items 4–7: blocking for correct device lifecycle.
Item 8: should be done before deploying any queue code.
Items 9–12: the queue feature, shippable independently of 4–7.
Item 13: system health UI, follows after admin findings table exists.
