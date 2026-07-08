# Platform Implementation Blueprint

Implement `operations/DESIGN.md` in full, in the correct dependency order.
Each phase is independently deployable and verifiable before proceeding.
No guessing. Every spec is derived from current code, not assumptions.

---

## Existing state (verified from code — do not rebuild)

| What | Location | Notes |
|---|---|---|
| `entity_observations` | `operations.entity_observations` | Django model ✓ |
| `finding_types` (10 seeded) | `operations.finding_types` (FindingType model) | Missing finding_class, source_module, auto_resolvable |
| `findings` | `operations.findings` (Finding model) | Missing condition_key, confidence, last_detected_at, client FK |
| `notification_routes` | `operations.notification_routes` (NotificationRoute model) | Delivery channel. New NotificationRule (rule engine) is separate. |
| `suppression_rules` | `operations.suppression_rules` (SuppressionRule model) | This IS DESIGN's finding_suppressions. Keep name. |
| `device_links` | `operations.device_links` (DeviceLink model) | Has first_seen_at, last_seen_at already. Needs missing_since only. |
| `devices` | `operations.devices` (Device model) | Has deleted_at. Needs 6 more lifecycle columns. |
| `clients` | `operations.clients` (Client model) | Has deleted_at. Needs 6 more lifecycle columns. |
| `software_installations_current` | `operations.software_installations_current` | Created in Django migration 0004. Has no stale/deleted columns yet. |
| `refresh_software_installations_current()` | defined in migration 0004 | Currently DELETEs missing rows. Needs three-state rewrite. |
| Software ingest | `ingest/inventory/software.py` | Writes to entity_observations ✓ |
| Queue tables | `ninja_core.software_{scheduled,demand,activity}_queue` | Migration 069 ✓ |
| Queue workers | `ingest/inventory/queue.py` | drain_background, process_demand ✓ |
| S1 connector | `ingest/agent_compliance/clients/sentinelone.py` | Needs dual-write to entity_observations |
| SC connector | `ingest/agent_compliance/clients/screenconnect.py` | Needs dual-write to entity_observations |
| Ninja device ingest | `ingest/core/devices.py` | Sets ninja_core.devices.missing_since ✓. Needs operations sync added. |

---

## Phase 1 — Software three-state staleness
**Django migration 0011 (RunSQL)**

### Columns to add to `operations.software_installations_current`
```sql
ALTER TABLE operations.software_installations_current
    ADD COLUMN IF NOT EXISTS stale_since   TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS stale_reason  TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS deleted_at    TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deleted_reason TEXT NOT NULL DEFAULT '';
```

### Rewrite `operations.refresh_software_installations_current()`
Replace the existing function body. The INSERT/ON CONFLICT block stays unchanged.
Remove the DELETE step. Add instead:

```sql
-- Step 2: mark stale
UPDATE operations.software_installations_current t
SET stale_since  = now(),
    stale_reason = 'ninja.ingest.observation_missing'
WHERE (p_tenant_id IS NULL OR t.tenant_id = p_tenant_id)
  AND t.stale_since IS NULL
  AND t.deleted_at IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM operations.entity_observations o
      WHERE o.entity_type = 'software'
        AND o.tenant_id   = t.tenant_id
        AND o.client_id   = t.client_id
        AND o.device_id   = t.device_id
        AND o.entity_key  = t.canonical_name
  );

-- Step 3: unmark stale (observation reappeared)
UPDATE operations.software_installations_current t
SET stale_since  = NULL,
    stale_reason = ''
WHERE (p_tenant_id IS NULL OR t.tenant_id = p_tenant_id)
  AND t.stale_since IS NOT NULL
  AND t.deleted_at IS NULL
  AND EXISTS (
      SELECT 1 FROM operations.entity_observations o
      WHERE o.entity_type = 'software'
        AND o.tenant_id   = t.tenant_id
        AND o.client_id   = t.client_id
        AND o.device_id   = t.device_id
        AND o.entity_key  = t.canonical_name
  );
```

### File to create
`operations/apps/core/migrations/0011_software_staleness.py` — RunPython wrapping RunSQL (same pattern as 0004).

### Verify after deploy
```sql
SELECT stale_since IS NOT NULL AS stale, COUNT(*)
FROM operations.software_installations_current GROUP BY 1;
```
Stale rows appear after the next software ingest if any device has been removed from scope.

---

## Phase 2 — Device and client lifecycle columns
**Django migration 0012**

### Model changes in `operations/apps/core/models.py`

**DeviceLink** — add one field:
```python
missing_since = models.DateTimeField(null=True, blank=True)
```

**Device** — add six fields (deleted_at already exists):
```python
created_at     = models.DateTimeField(auto_now_add=True)
created_reason = models.CharField(max_length=120, blank=True, default='')
updated_at     = models.DateTimeField(auto_now=True)
updated_reason = models.CharField(max_length=120, blank=True, default='')
stale_since    = models.DateTimeField(null=True, blank=True)
stale_reason   = models.CharField(max_length=120, blank=True, default='')
deleted_reason = models.CharField(max_length=120, blank=True, default='')
```

**Client** — same six fields as Device (deleted_at already exists).

### File to create
Run `python manage.py makemigrations operations --name lifecycle_columns` after model edits.
Output: `operations/apps/core/migrations/0012_lifecycle_columns.py`

No RLS changes needed — existing policies on device_links, devices, clients cover new columns automatically.

### Verify
```bash
python manage.py check
python manage.py migrate operations
```

---

## Phase 3 — Extend FindingType and Finding; seed new finding types
**Django migration 0013**

### FindingType — add three fields in `models.py`
```python
class FindingClass(models.TextChoices):
    ENTITY = 'entity', 'Entity'
    ADMIN  = 'admin',  'Admin'

finding_class   = models.CharField(max_length=16, choices=FindingClass.choices, default='entity')
source_module   = models.CharField(max_length=80, blank=True, default='')
auto_resolvable = models.BooleanField(default=True)
```

### Finding — add four fields in `models.py`
```python
condition_key    = models.CharField(max_length=255, blank=True, default='', db_index=True)
confidence       = models.CharField(
    max_length=16,
    choices=[('possible','Possible'),('probable','Probable'),('confirmed','Confirmed')],
    blank=True, default='',
)
last_detected_at = models.DateTimeField(null=True, blank=True)
client           = models.ForeignKey(
    'Client', on_delete=models.PROTECT, null=True, blank=True, related_name='findings'
)
```

Add partial UniqueConstraint to Finding.Meta:
```python
models.UniqueConstraint(
    fields=['tenant', 'condition_key'],
    condition=models.Q(condition_key__gt='') & models.Q(status__in=['open', 'acknowledged']),
    name='uq_findings_active_condition_key',
)
```

### RunPython: update existing FindingType rows
For each of the 10 existing types (seeded in 0007): set `finding_class='entity'`, `auto_resolvable=True`.
Source module by type:
- unlinked_external_identity → `'identity.resolver'`
- stale_collector_binding → `'queue.health'`
- unauthorized_rmm, unauthorized_av, unauthorized_remote_access, install_path_suspicious, rare_recent, eol_runtime, suspicious_name, multi_av_conflict → `'inventory.software'`

### RunPython: new finding types to seed
```python
NEW_FINDING_TYPES = (
    # (name, default_severity, description, finding_class, source_module, auto_resolvable)
    ('device_missing_from_source',    'high',   'Device disappeared from source API',        'entity', 'ninja.ingest',        True),
    ('device_long_offline',           'medium', 'Device offline for extended period',         'entity', 'ninja.ingest',        True),
    ('device_stale_data',             'low',    'Device data not refreshed recently',         'entity', 'ninja.ingest',        True),
    ('missing_required_platform',     'high',   'Required coverage platform not observed',    'entity', 'platform.evaluator',  True),
    ('software_queue_stalled',        'high',   'Software refresh queue stalled',             'admin',  'queue.health',        False),
    ('identity_resolution_pending',   'low',    'Devices awaiting identity resolution',       'admin',  'identity.resolver',   False),
)
```

### File to create
Run `python manage.py makemigrations operations --name finding_extensions` after model edits.
Then add RunPython calls to the generated migration file manually.

### Verify
```sql
SELECT finding_class, COUNT(*) FROM operations.finding_types GROUP BY 1;
-- entity: ~16, admin: 2
SELECT name FROM operations.finding_types WHERE finding_class = 'admin';
```

---

## Phase 4 — New platform tables
**Django migration 0014**

### New models — add all to `operations/apps/core/models.py`

Use `Severity` and `Status` choices already defined on `Finding` — extract them to module level so they can be reused:
```python
class Severity(models.TextChoices):
    CRITICAL = 'critical', 'Critical'
    HIGH = 'high', 'High'
    MEDIUM = 'medium', 'Medium'
    LOW = 'low', 'Low'
    INFO = 'info', 'Info'

class FindingStatus(models.TextChoices):
    OPEN = 'open', 'Open'
    ACKNOWLEDGED = 'acknowledged', 'Acknowledged'
    RESOLVED = 'resolved', 'Resolved'
```
(Keep existing inner classes on Finding as aliases pointing to these.)

**CoverageRequirement**
```python
class CoverageRequirement(TenantScopedModel):
    id                   = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client               = models.ForeignKey('Client', on_delete=models.PROTECT, null=True, blank=True, related_name='coverage_requirements')
    entity_type          = models.CharField(max_length=80)
    platform             = models.CharField(max_length=80, blank=True, default='')
    device_scope         = models.CharField(max_length=40, default='all')  # 'all'|'servers'|'workstations'
    severity             = models.CharField(max_length=16, choices=Severity.choices, default='high')
    gap_after_hours      = models.PositiveIntegerField(default=24)
    confidence_probable  = models.PositiveIntegerField(default=48)
    confidence_confirmed = models.PositiveIntegerField(default=168)
    enabled              = models.BooleanField(default=True)
    created_at           = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'coverage_requirements'
```

**AdminFinding**
```python
class AdminFinding(TenantScopedModel):
    id                = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    finding_type      = models.ForeignKey('FindingType', on_delete=models.PROTECT, related_name='admin_findings')
    condition_key     = models.CharField(max_length=255)
    severity          = models.CharField(max_length=16, choices=Severity.choices, default='medium')
    status            = models.CharField(max_length=24, choices=FindingStatus.choices, default='open')
    subject_ref       = models.JSONField(default=dict)
    details           = models.JSONField(default=dict)
    first_detected_at = models.DateTimeField()
    last_detected_at  = models.DateTimeField()
    resolved_at       = models.DateTimeField(null=True, blank=True)
    class Meta:
        db_table = 'admin_findings'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'condition_key'],
                condition=models.Q(status__in=['open', 'acknowledged']),
                name='uq_admin_findings_active_condition_key',
            )
        ]
```

**QueueRegistry** (not tenant-scoped — global operator table)
```python
class QueueRegistry(models.Model):
    queue_key         = models.CharField(max_length=120, primary_key=True)
    queue_type        = models.CharField(max_length=16)  # 'refresh'|'processing'
    table_name        = models.CharField(max_length=120)
    owner             = models.CharField(max_length=80)
    enabled           = models.BooleanField(default=True)
    max_pending_age_m = models.PositiveIntegerField(default=60)
    max_failure_count = models.PositiveIntegerField(default=5)
    max_depth         = models.PositiveIntegerField(default=1000)
    description       = models.TextField(blank=True)
    class Meta:
        db_table = 'queue_registry'
        app_label = 'operations'
```

Seed RunPython for existing queues:
```python
QUEUE_SEEDS = (
    ('software.scheduled', 'refresh', 'ninja_core.software_scheduled_queue', 'ninja.ingest', 'Scheduled per-org software pull'),
    ('software.demand',    'refresh', 'ninja_core.software_demand_queue',    'ninja.ingest', 'On-demand operator-triggered software pull'),
    ('software.activity',  'refresh', 'ninja_core.software_activity_queue',  'ninja.ingest', 'Activity-triggered per-device software pull'),
)
```

**IdentityCandidate**
```python
class IdentityCandidate(TenantScopedModel):
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_a    = models.ForeignKey('Device', on_delete=models.PROTECT, related_name='identity_candidates_a')
    device_b    = models.ForeignKey('Device', on_delete=models.PROTECT, related_name='identity_candidates_b')
    confidence  = models.CharField(max_length=16)  # 'high'|'medium'|'low'
    signals     = models.JSONField(default=dict)
    status      = models.CharField(max_length=16, default='pending')  # pending|confirmed|rejected
    created_at  = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.CharField(max_length=120, blank=True)
    class Meta:
        db_table = 'identity_candidates'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'device_a', 'device_b'],
                condition=models.Q(status='pending'),
                name='uq_identity_candidates_pending_pair',
            )
        ]
```

**NotificationRule** (NEW — rule engine; existing NotificationRoute is the delivery channel, unchanged)
```python
class NotificationRule(TenantScopedModel):
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    finding_type   = models.ForeignKey('FindingType', on_delete=models.PROTECT, related_name='notification_rules')
    finding_class  = models.CharField(max_length=16, default='entity')
    min_severity   = models.CharField(max_length=16, blank=True, default='')
    min_confidence = models.CharField(max_length=16, blank=True, default='')
    client         = models.ForeignKey('Client', on_delete=models.PROTECT, null=True, blank=True, related_name='notification_rules')
    match_criteria = models.JSONField(default=dict)
    route          = models.ForeignKey('NotificationRoute', on_delete=models.PROTECT, related_name='rules')
    urgency_hours  = models.PositiveIntegerField(null=True, blank=True)
    cooldown_hours = models.PositiveIntegerField(default=24)
    enabled        = models.BooleanField(default=True)
    class Meta:
        db_table = 'notification_rules'
```

**NotificationState**
```python
class NotificationState(TenantScopedModel):
    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fingerprint     = models.CharField(max_length=255)
    rule            = models.ForeignKey('NotificationRule', on_delete=models.PROTECT, related_name='state_entries')
    last_sent_at    = models.DateTimeField()
    next_allowed_at = models.DateTimeField()
    send_count      = models.PositiveIntegerField(default=1)
    class Meta:
        db_table = 'notification_state'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant', 'fingerprint', 'rule'],
                name='uq_notification_state_fingerprint_rule',
            )
        ]
```

**NotificationEvent**
```python
class NotificationEvent(TenantScopedModel):
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    rule        = models.ForeignKey('NotificationRule', on_delete=models.PROTECT, null=True, blank=True, related_name='events')
    fingerprint = models.CharField(max_length=255)
    channel     = models.CharField(max_length=16)
    status      = models.CharField(max_length=16)  # sent|failed|suppressed
    payload_ref = models.JSONField(default=dict)
    error       = models.TextField(blank=True)
    sent_at     = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'notification_events'
        indexes = [models.Index(fields=['tenant', 'sent_at'], name='idx_notif_events_sent_at')]
```

### RLS (RunSQL in migration 0014)
For each new tenant-scoped table (coverage_requirements, admin_findings, identity_candidates, notification_rules, notification_state, notification_events), issue:
```sql
ALTER TABLE operations.<table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.<table> FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON operations.<table>;
CREATE POLICY tenant_isolation ON operations.<table>
    USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
ALTER TABLE operations.<table> OWNER TO operations_migrate;
GRANT INSERT, SELECT, UPDATE, DELETE ON operations.<table> TO operations_app, ninja_ingest;
GRANT SELECT ON operations.<table> TO operations_readonly, metabase_ro;
```
`queue_registry` has no tenant_id — no RLS. Grant SELECT, INSERT, UPDATE, DELETE to operations_app, ninja_ingest.

### File to create
`python manage.py makemigrations operations --name platform_tables` + add RunSQL + RunPython manually.

### Verify
```sql
\dt operations.*
SELECT queue_key, enabled FROM operations.queue_registry ORDER BY queue_key;
```

---

## Phase 5 — Operations DeviceLink reconciliation
**Ingest code: `ingest/core/devices.py`**

### Add function `_sync_operations_device_links`

Called inside the same `with db.transaction() as cur:` block, after `_mark_missing_devices`. Pass `current_ids_text = [str(i) for i in current_ids]`.

The function must set the GUC before touching operations.*:
```python
cur.execute("SET LOCAL operations.tenant_id = 1")
```

Then three UPDATE statements:

```sql
-- 1. Refresh last_seen_at for devices still present
UPDATE operations.device_links dl
SET last_seen_at = %(snapshot_at)s
FROM operations.sources s
WHERE dl.source_id = s.id AND s.name = 'Ninja'
  AND dl.external_id = ANY(%(ids)s)
  AND dl.missing_since IS NULL;

-- 2. Mark devices that disappeared
UPDATE operations.device_links dl
SET missing_since = %(snapshot_at)s
FROM operations.sources s
WHERE dl.source_id = s.id AND s.name = 'Ninja'
  AND NOT (dl.external_id = ANY(%(ids)s))
  AND dl.missing_since IS NULL;

-- 3. Clear missing_since for devices that reappeared
UPDATE operations.device_links dl
SET missing_since = NULL
FROM operations.sources s
WHERE dl.source_id = s.id AND s.name = 'Ninja'
  AND dl.external_id = ANY(%(ids)s)
  AND dl.missing_since IS NOT NULL;
```

**DEPENDENCY**: Phase 2 must be deployed first (missing_since column must exist).

### Verify
```sql
SELECT missing_since IS NOT NULL AS missing, COUNT(*)
FROM operations.device_links dl
JOIN operations.sources s ON s.id = dl.source_id AND s.name = 'Ninja'
GROUP BY 1;
```

---

## Phase 6 — Identity resolver
**New package `ingest/identity/`**

### Files

**`ingest/identity/__init__.py`** — empty

**`ingest/identity/fast_path.py`**

```python
def resolve_device_fast(
    cur,  # open psycopg cursor with GUC already set
    tenant_id: int,
    source_name: str,
    external_id: str,
    serial: str | None = None,
    hostname: str | None = None,
) -> uuid.UUID | None
```

Step 1 — exact source+external_id match (certain):
```sql
SELECT dl.device_id FROM operations.device_links dl
JOIN operations.sources s ON s.id = dl.source_id
WHERE dl.tenant_id = %s AND s.name = %s AND dl.external_id = %s
LIMIT 1
```

Step 2 — serial match (high confidence, unique):
```sql
SELECT id FROM operations.devices
WHERE tenant_id = %s AND canonical_serial = %s AND deleted_at IS NULL
```
Only return if exactly 1 row.

Step 3 — hostname match (medium-high, unique):
```sql
SELECT id FROM operations.devices
WHERE tenant_id = %s AND canonical_hostname = %s AND deleted_at IS NULL
```
Only return if exactly 1 row AND no existing device_link for this source+external_id.

Returns None on miss. Caller enqueues to identity_resolution_queue (future: add to QueueRegistry in Phase 4 seed).

**`ingest/identity/resolver.py`**

```python
def drain_resolution(batch_size: int = 20) -> int
```

Fetches `entity_observations WHERE device_id IS NULL LIMIT batch_size` (with GUC set).
For each: tries normalized hostname match (lowercase, strip domain suffix).
- Unique match: `UPDATE entity_observations SET device_id = %s`.
- Multiple candidates: INSERT into identity_candidates (status='pending').
- No match: skip (periodic sweep will retry).

Returns count resolved.

Add `identity.resolution` to QueueRegistry seed in Phase 4:
```python
('identity.resolution', 'processing', 'operations.entity_observations', 'identity.resolver', 'Resolve device_id on unresolved observations')
```

**DEPENDENCY**: Phase 4 (IdentityCandidate table) must be deployed first.

---

## Phase 7 — S1 and SC connectors → entity_observations
**Migration 0015 + connector code changes**

### Migration 0015 — seed S1, SC, LogMeIn source bindings

Fixed UUIDs:
```python
S1_SOURCE_BINDING_ID      = uuid.UUID("00000000-0000-4000-8000-000000000012")
SC_SOURCE_BINDING_ID      = uuid.UUID("00000000-0000-4000-8000-000000000013")
LOGMEIN_SOURCE_BINDING_ID = uuid.UUID("00000000-0000-4000-8000-000000000014")
```

RunPython: for each source (SentinelOne, ScreenConnect, LogMeIn):
1. `Source.objects.update_or_create(name=..., defaults={'kind': 'edr'|'remote_access'|'remote_access', ...})`
2. `SourceInstance.objects.update_or_create(...)` (tenant-scoped, no client)
3. `SourceBinding.objects.update_or_create(id=fixed_uuid, ...)`

RunSQL: `GRANT SELECT ON operations.devices, operations.device_links TO ninja_ingest;` (if not already granted).

### Connector changes

**`ingest/agent_compliance/clients/sentinelone.py`**

Import at top:
```python
from ingest.identity.fast_path import resolve_device_fast
from ingest import db
from psycopg.types.json import Json
import uuid, hashlib, logging
from datetime import datetime, timezone

TENANT_ID = 1
S1_SOURCE_BINDING_ID = uuid.UUID("00000000-0000-4000-8000-000000000012")
INTERNAL_COLLECTOR_INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
```

After the existing write to `ninja_agent_compliance.platform_observations`, also write to `operations.entity_observations`:
- `entity_type = 'agent.edr'`
- `entity_key = agent["uuid"]` (S1's stable agent UUID)
- `platform = 'SentinelOne'`
- `observed_at = datetime.now(timezone.utc)`
- `device_id = resolve_device_fast(cur, 1, 'SentinelOne', agent['uuid'], serial, hostname)` — may be None
- `canonical_data = {'name': 'SentinelOne', 'version': agent.get('agentVersion'), 'status': agent.get('isActive'), 'policy': agent.get('policyName')}`
- `observation_hash = sha256(f"{agent['uuid']}:{agent.get('agentVersion', '')}".encode()).digest()`

Use `db.insert_ignore(cur, 'operations.entity_observations', rows, conflict_keys=['tenant_id','collector_instance_id','batch_id','observation_hash'])`.
Must SET LOCAL operations.tenant_id = 1 before this INSERT.

Keep existing platform_observations write in parallel (dual-write) until Phase 9 validates.

**`ingest/agent_compliance/clients/screenconnect.py`**

Same pattern:
- `entity_type = 'agent.remote_access'`
- `entity_key = session['SessionID']` (SC's stable session GUID)
- `platform = 'ScreenConnect'`
- `canonical_data = {'name': 'ScreenConnect', 'version': session.get('ClientVersion'), 'guest_name': session.get('Name'), 'machine_name': session.get('GuestMachineName')}`
- `device_id = resolve_device_fast(cur, 1, 'ScreenConnect', session['SessionID'], serial=None, hostname=session.get('GuestMachineName'))`

**DEPENDENCY**: Phase 6 (fast_path) must exist. Migration 0015 (SourceBindings) must be deployed.

### Verify
```sql
SELECT entity_type, platform, COUNT(*),
       SUM(CASE WHEN device_id IS NULL THEN 1 ELSE 0 END) AS unresolved
FROM operations.entity_observations
GROUP BY 1, 2;
```

---

## Phase 8 — Platform evaluator
**New file `ingest/evaluator.py`**

### Interface
```python
def evaluate(tenant_id: int, device_id: uuid.UUID | None = None) -> int
```
Returns number of findings opened or updated.
`device_id = None` → evaluate all devices for this tenant.

### Logic skeleton
```python
def evaluate(tenant_id: int, device_id: uuid.UUID | None = None) -> int:
    # 1. Load coverage requirements
    # 2. For each requirement, resolve device scope to list of device UUIDs
    # 3. For each device:
    #    a. find latest observation for (device, entity_type, platform)
    #    b. compute gap_age = now() - last_observed_at  (or since device.created_at if never seen)
    #    c. skip if gap_age < requirement.gap_after_hours
    #    d. compute confidence from gap thresholds
    #    e. condition_key = sha256(f"{tenant_id}:{client_id}:{device_id}:{entity_type}:{platform}")[:64]
    #    f. UPSERT finding (INSERT on conflict update confidence+last_detected_at only; severity immutable)
    # 4. For devices with device_links.missing_since set: open device_missing_from_source finding
    # 5. For devices offline > 7d: open device_long_offline finding
    # 6. For findings where condition clears: UPDATE status='resolved'
    return findings_affected
```

Uses `db.pool.connection()` directly (not db.transaction) to allow partial commits.
Must SET LOCAL operations.tenant_id = tenant_id before any operations.* query.

**DEPENDENCY**: Phase 3 (condition_key on Finding), Phase 4 (CoverageRequirement table).

### Schedule in `ingest/main.py`
- After each activity ingest run: `evaluate(tenant_id=1)`
- Sweep: add APScheduler job every 4 hours: `evaluate(tenant_id=1)`

---

## Phase 9 — Compliance engine rebuild
**Modify `ingest/agent_compliance/ingest.py`**

Replace internal gap analysis inside `evaluate()` with:
```python
from ingest.evaluator import evaluate
evaluate(tenant_id=1)
```

Keep the call to `ingest.inventory.refresh.run()` and SC/S1 data pulls.
Keep writing to `ninja_agent_compliance.current_device_states` if it's still read by AC Metabase dashboards.
**Do not remove** the existing `ninja_agent_compliance.platform_observations` dual-write until user explicitly approves.

---

## Phase 10 — agent_presence_current
**Django migration 0016 (RunSQL)**

```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS operations.agent_presence_current AS
SELECT
    o.tenant_id,
    o.client_id,
    o.device_id,
    o.entity_type,
    o.platform,
    o.subplatform,
    MAX(o.observed_at)  AS last_observed_at,
    MIN(o.observed_at)  AS first_observed_at,
    COUNT(*)            AS observation_count
FROM operations.entity_observations o
WHERE o.entity_type LIKE 'agent.%'
  AND o.device_id IS NOT NULL
GROUP BY o.tenant_id, o.client_id, o.device_id,
         o.entity_type, o.platform, o.subplatform
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_presence_pk
    ON operations.agent_presence_current (tenant_id, device_id, entity_type, platform);

CREATE OR REPLACE FUNCTION operations.refresh_agent_presence_current()
RETURNS void LANGUAGE plpgsql AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY operations.agent_presence_current;
END;
$$;
```

Call `operations.refresh_agent_presence_current()` at end of each S1 and SC connector run.

---

## Phase 11 — Findings review page + admin health page
**Django views + templates**

### URL map
```
/findings/                  → findings_review (entity findings)
/admin/findings/health/     → findings_admin_health (admin findings)
```

### findings_review view
Query: `Finding.objects.select_related('finding_type','client').filter(tenant=..., status__in=['open','acknowledged'])`.
Filters (GET params): finding_type, finding_class, severity, confidence, client_id.
Order: severity priority (critical→info) DESC, last_detected_at DESC.
Pagination: 50 per page.

### findings_admin_health view
Query: `AdminFinding.objects.select_related('finding_type').filter(tenant=..., status__in=['open','acknowledged'])`.
No client filter (admin findings are platform-wide).

### Templates
Extend `base.html`. Use existing card/table style from device_list.html.
Show: finding_type name, subject (device hostname or client name), severity badge, confidence, status, first/last detected.
Action: acknowledge button (POST to `/findings/<id>/ack/`).

### Additional URL + view needed
```
POST /findings/<uuid>/ack/  → set status='acknowledged', return 302 back to findings list
POST /admin/findings/<uuid>/ack/ → same for AdminFinding
```

---

## Phase 12 — Docker service rename
**Independent — safe to do at any time**

In `docker-compose.yml`: rename service key `ninja-ingest:` → `operations-ingest:`.
Check `depends_on:` in other services for `ninja-ingest` references and update them.

Verify: after Portainer redeploy, `docker ps` shows `operations-ingest` container.

---

## Phase 13 — DB role rename
**Django migration 0017 (RunSQL)**

```sql
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'operations_ingest') THEN
        CREATE ROLE operations_ingest;
    END IF;
END $$;
```

Then re-issue every GRANT previously given to `ninja_ingest`, substituting `operations_ingest`.
Then check for active connections: `SELECT COUNT(*) FROM pg_stat_activity WHERE usename = 'ninja_ingest'` — must be 0.
Then: `DROP ROLE IF EXISTS ninja_ingest;`

**WARNING**: Coordinate this with `.env` on am-ch-01. The ingest container must use `operations_ingest` credentials BEFORE the old role is dropped. Update `.env` first, redeploy, verify connectivity, then drop old role in a second migration.

---

## Phase 14 — Schema rename (ninja_agent_compliance → agent_compliance)
**Last step — do after all code references are updated**

Pre-condition: `rg "ninja_agent_compliance" --type py --type sql` returns zero hits in all Python and SQL files.
Only then: `ALTER SCHEMA ninja_agent_compliance RENAME TO agent_compliance;` in Django migration 0018 (RunSQL).

---

## Deployment batches

| Batch | Phases | Can ship together |
|---|---|---|
| A | 1, 2, 3, 4 | Yes — pure schema/model additions, no logic dependencies between them |
| B | 5, 6, 7 | Yes — devices.py sync + identity fast_path + S1/SC dual-write (migration 0015 in same batch) |
| C | 8, 9, 10 | Yes — evaluator + compliance rebuild + agent_presence_current |
| D | 11 | Findings review pages (can go with C or separately) |
| E | 12, 13, 14 | Naming cleanup — last |

Batch A unblocks all subsequent batches.
Each batch is a single `git push` + Portainer redeploy + verify step.

---

## Pre-push checklist (for every batch)

- [ ] `python manage.py check` passes with zero errors
- [ ] `python manage.py showmigrations operations` shows all new migrations unapplied
- [ ] All new file paths exist (no missing imports)
- [ ] RLS granted on every new tenant-scoped table
- [ ] No `ninja_agent_compliance` reference in changed files (grep before commit)
- [ ] Dockerfile COPY still covers all source directories (no new top-level dirs added without COPY)
