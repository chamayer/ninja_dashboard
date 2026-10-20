# Troubleshooting Session — device id 4042 shows "Never Patched"

> Working notes. No code changes during this session. Findings get
> migrated to a proper fix once root cause is confirmed.

---

## Problem statement

Device id **4042** is classified as **Never-Patched** on the
dashboards, but the operator can see plenty of patch activity for
that device in the activities feed.

This means our "Never Patched" classification disagrees with what
Ninja's activity stream is reporting. Either:

1. The activities table HAS patch events for device 4042 but our
   `patch_facts` table doesn't have any `install_outcome` rows for
   it → classification logic is correct, but ingest from
   `/queries/os-patch-installs` is missing this device.
2. There ARE install_outcome rows in patch_facts but the
   classification CTE is filtering them out (e.g. NULL
   `installed_at`, wrong `fact_type`, wrong `status`).
3. Activity row count is misleading the operator (e.g. lots of
   `PATCH_MANAGEMENT_MESSAGE` rows that don't represent installs).

## Investigation log

### Step 1 — recent activities for device 4042 (Q1 below)

19 rows returned, all within 2026-06-03 → 2026-06-05.
Bucketed:

| Bucket | Count | What it means |
|---|---|---|
| `*_SCAN_STARTED` / `*_SCAN_COMPLETED` (source=PATCH_MANAGEMENT) | 2 | Ninja scanned the device for missing patches. **Not an install.** |
| `STARTED` / `COMPLETED` (source=ACTION) | 14 | Ninja **Actions** (RMM scripts) ran on the device: BitLocker key collector, FW status, Defender status, Office version reader. **Not OS patches.** |
| `START_REQUESTED` (source=ACTIONSET) | 1 | Operator triggered an Action manually. **Not an install.** |
| `SOFTWARE_UPDATED` / `SOFTWARE_PATCH_MANAGEMENT_INSTALL_FAILED` | 2 | Both rows reference `NinjaRMMAgent, Version: 13.0.7941` — the Ninja **agent self-updated**, not a Windows OS patch. |

**Zero** `PATCH_MANAGEMENT_APPLY_PATCH_STARTED` /
`PATCH_MANAGEMENT_APPLY_PATCH_COMPLETED` rows.

**Interpretation:** the operator's "lots of patch activity" is
mostly scans + RMM Actions + an agent self-update. None of those
are OS patch installs. So "Never-Patched" in the dashboard might
in fact be correct for device 4042 — Ninja has been polling the
device but no OS patches have actually been applied.

Still need to verify there isn't install data in `patch_facts`
that the activities feed isn't surfacing (some Ninja deployments
write install rows without emitting an activity).

### Hypotheses tracker update

- [x] **H4 — disproved**: operator says Ninja GUI shows
       significantly more patch-management activity for device
       4042 than the 3 rows our DB returned. So the operator
       isn't misreading; we're missing rows.
- [ ] H1: ingest missed install_outcome rows.
- [ ] H2: install_outcome rows exist but `installed_at` is NULL.
- [ ] H3: classification CTE filters them out.
- [ ] **H5 — new**: ingest config `INGEST_ACTIVITY_TYPES_INCLUDE`
       is filtering out the codes the operator sees in Ninja GUI
       (we know default example omits SCAN codes; user may have
       set their own narrow allowlist).
- [ ] **H6 — new**: ingest cursor is recent; activities older
       than the first run aren't pulled. Device 4042 might have
       had its installs before our forward-walking ingest
       started.

### Step 2 — diagnostic results

**(A) distinct codes in DB** — 96 distinct codes ingested across
the whole DB. We DO have `PATCH_MANAGEMENT_APPLY_PATCH_STARTED`
(795 rows) and `PATCH_MANAGEMENT_APPLY_PATCH_COMPLETED` (795
rows). So our ingest filter is wide and patch-install events
ARE coming through for SOME devices, just not device 4042.

**(B) cursor / range**
- cursor_last_id = 70725866 (most recent we've ingested)
- oldest_id_in_db = 70560330
- oldest_time_in_db = **2026-05-28** (≈ 8 days ago)
- oldest_id for device 4042 = 70612274 (within our window)

So we cover the last ~8 days only. Anything older requires the
backfill script (`ingest.activities.backfill`).

**(C) env**
- `docker exec operations-ingest env | grep INGEST_ACTIVITY` returned
  nothing — vars aren't in process env. Probably loaded from
  `/app/.env` via dotenv. Not blocking — (A) already proves the
  filter is wide.

### Key reframe

The dashboard's "Never-Patched" badge does NOT read activities.
It reads `ninja_patches.patch_facts` for rows with
`fact_type='install_outcome' AND installed_at IS NOT NULL`. The
ingest source for those is `/queries/os-patch-installs`, NOT
the activities feed. So "lots of activities in Ninja GUI" ≠
"installs in our patch_facts".

The question to answer now: does `patch_facts` have any
install_outcome rows for device 4042?

### Step 3 — patch_facts for device 4042 — RESULTS

**(D)** Device 4042 has patch_facts rows:

| fact_type | status | rows | rows_with_installed_at |
|---|---|---|---|
| install_outcome | INSTALLED | 3 | **0** |
| patch_state | APPROVED | 13 | 0 |
| patch_state | DELAYED | 2 | 0 |
| patch_state | REJECTED | 2 | 0 |

**Root cause confirmed.** Device 4042 HAS install_outcome INSTALLED
rows, but `installed_at` is NULL on all 3. The dashboard
classification CTE explicitly filters those out:

```sql
WHERE fact_type = 'install_outcome' AND installed_at IS NOT NULL
```

→ device 4042 appears never-patched.

**(E2)** Across the whole DB:
- install_outcome rows: 376,903 / 2,784 devices
- earliest install: 2010-11-20 (suspiciously old — probably a
  malformed timestamp from one record; not blocking)
- latest install: 2026-06-05 (today)

So timestamps DO come through correctly for most rows. NULL is the
exception, not the rule.

**(F)** Failed: `needs_reboot` column doesn't exist on
`ninja_core.devices`. Probably lives on `device_snapshots`.
Side-issue; logged for later cleanup.

### Hypotheses tracker

- [x] **H2 — confirmed**: install_outcome rows exist for device
       4042 but with NULL installed_at; classification CTE
       filters them out → "Never-Patched" misclassification.
- [ ] open: WHY is installed_at NULL for these specific rows?
       Likely Ninja's `/queries/os-patch-installs` returned
       NULL for `installedAt` on these records. Need to look
       at the raw `data` jsonb to confirm.
- [ ] open: how many devices are misclassified fleet-wide for
       the same reason?

### Step 4 — RESULTS: root cause confirmed

**(G) fleet-wide scale**: 376,698 INSTALLED rows; **4,394 (1.2 %)
have NULL installed_at**.

**(H) devices misclassified**:
- only_null_devices = **6** ← misclassified as "Never-Patched"
- mixed_devices = 871 (still classify correctly via the valid rows)
- only_valid_devices = 1,907
- total devices with installs = 2,784

So fleet-wide, **6 devices** are misclassified as Never-Patched
because every install row they have lacks a timestamp. Device 4042
is one of them.

**(I) raw data for device 4042's 3 INSTALLED records**:

```json
{"id":"...","name":"2022-12 Security Update ... KB5012170",
 "type":"SECURITY_UPDATES","status":"INSTALLED","deviceId":4042,
 "kbNumber":"KB5012170","severity":"NONE","timestamp":1777176140.0}
```

`installedAt` field is **absent** from the Ninja API response.
Only `timestamp` (= data collection time, 2026-04-26) is present.
Ninja's `/queries/os-patch-installs` endpoint omits installedAt
for some records — likely very-old historical installs where
Ninja knows the patch is installed but lacks the precise install
time. (KB5012170 dates from 2022-12; MSXML 6.0 is ancient.)

### Root cause

Three layers of the chain:

1. **Ninja API**: returns `status="INSTALLED"` for old historical
   patches without an `installedAt` value.
2. **Ingest**: correctly stores NULL since the field is absent.
3. **Classification CTE** (in
   `metabase_bootstrap.py`'s `cmd_patching`, `cmd_stale`,
   `cmd_never`, etc.):
   ```sql
   WHERE fact_type = 'install_outcome' AND installed_at IS NOT NULL
   ```
   Filters out NULL-installed_at rows. For devices whose only
   INSTALLED rows have NULL installed_at, the CTE returns nothing
   → device classified as never-patched.

### Proposed fix (next session, with blueprint)

**(C) defense-in-depth — both ingest and dashboard sides:**

- **Ingest** (`ingest/patches/ingest.py`): when Ninja's record
  lacks `installedAt`, fall back to the `timestamp` field
  (Ninja's data-collection timestamp) so `installed_at` is
  populated for new rows. One-time UPDATE backfills the existing
  4,394 NULL rows from the `data` jsonb.
- **Dashboard** (`metabase_bootstrap.py`): change the
  classification CTE to use
  `COALESCE(installed_at, first_observed_at)` so devices whose
  install timestamps are genuinely unknown still classify based
  on when WE first saw them. Defense-in-depth: even if a future
  record arrives without either timestamp, we don't drop it.

### Step 5 — verify hypothesis manually

Hypothesis (operator): patches Ninja itself installed → have
`installedAt`. Patches installed by Windows Update / WSUS / OS
where Ninja just detects "this is installed now" → no
`installedAt`.

Plausible. Old KB numbers in the NULL bucket (KB5012170 from
2022-12, MSXML 6.0) reinforce this — likely OS-applied before
Ninja was watching.

Query pulls up to 3 rows of each bucket from 2 mixed-bucket
devices, including `system_name` for lookup in Ninja GUI.
Manual verification in progress.

*(waiting on operator's verdict from Ninja GUI)*

### Step 6 — hypothesis didn't hold; design decision

Manual verification: NULL-installed_at vs HAS-installed_at doesn't
correlate cleanly with Ninja-applied vs OS-applied. Theory rejected.

**Path forward (no code change today, plan for next session):**

For the **never-patched** classification — drop the
`installed_at IS NOT NULL` filter. Existence-only check fixes the
6 misclassified devices.

For **time-based buckets** (Patching Devices / Stalled Devices) —
use `COALESCE(installed_at, ninja_observed_at)` as the effective
install date. `ninja_observed_at` is honest because Ninja confirmed
the install was present at that scan time → lower-bound proof of
install. `first_observed_at` (when WE first ingested) rejected as
too misleading for old installs.

Optionally surface this in tables with a derived flag like
`install_time_estimated = (installed_at IS NULL)` so operators
can see when the date is a proxy.

### Patch category filtering — proposal

Currently no Patch Category filter on any dashboard. Ninja returns
a `type` field (e.g. `SECURITY_UPDATES`, `CRITICAL_UPDATES`) which
we store inside `patch_facts.data` (jsonb) but didn't promote to a
column.

Two paths when this gets prioritized:
- **Quick** — dashboard SQL extracts via `data->>'type'`, dashboard
  filter applies `[[AND data->>'type' IN ({{patch_category}})]]`.
- **Right** — new `patch_category` column on `patch_facts`,
  migration backfills from `data->>'type'`, ingest populates going
  forward. Indexable, faster, doesn't poke into jsonb on every
  query.

### Step 7 — patch category distribution

```
UNKNOWN              309,498   72.3%
DRIVER_UPDATES        38,548    9.0%
UNSPECIFIED           30,191    7.1%
SECURITY_UPDATES      20,718    4.8%
UPDATE_ROLLUPS        12,954    3.0%
CRITICAL_UPDATES       6,629    1.5%
REGULAR_UPDATES        4,929    1.2%
DEFINITION_UPDATES     3,129    0.7%
FEATURE_UPDATES        1,306    0.3%
SERVICE_PACKS            168
FEATURE_PACKS             84
                     -------
total                428,154
```

**~79 % of all patch_facts rows are UNKNOWN / UNSPECIFIED.** A
Patch Category filter would only narrow down ~21 % of the data;
operator would routinely have to "open the dustbin" to see what's
in there.

**Split by fact_type — answered:**

| Bucket | UNKNOWN+UNSPECIFIED | Categorized | Note |
|---|---|---|---|
| install_outcome (history) | 335,389 (89 %) | 41,514 (11 %) | Ninja mostly just records "installed"; no type for old / OS-applied patches |
| patch_state (pending) | 4,300 (8 %) | 46,951 (92 %) | Ninja categorizes pending patches well; ~70 % of pending are DRIVER_UPDATES |

The UNKNOWN concentration in install_outcome lines up with the
same pattern as the missing `installedAt`: for old / OS-applied
patches Ninja stores existence-only ("installed") without
category or install time. Ninja-managed installs have full
metadata (the 11 % categorized).

**Implications for filtering:**
- Patch Category filter is meaningfully useful on **patch_state**
  views (pending patches; categories largely known).
- Patch Category filter on install-history views is mostly noise.
- Operator surprise candidate: 70 % of pending patches are
  DRIVER_UPDATES. Might want a Driver-Updates toggle or a
  "Non-driver patches" view to deprioritize them.

**Operator decision (this session)**: drivers are not in scope
yet ("not installing drivers"). Don't render them in any
patch-context view.

**Recommended approach — hard exclude in SQL** (next-session
change, no code change today):

- Single module-level constant
  `EXCLUDE_PATCH_TYPES = ('DRIVER_UPDATES',)` at the top of
  `metabase_bootstrap.py`.
- Shared predicate fragment `_PATCH_TYPE_EXCLUDE` rendered from
  that constant. Empty when the tuple is empty (future opt-in).
- Append the fragment to every patch-context query's WHERE
  alongside the other `_*_FILTERS_*` constants.
- When drivers come in scope: empty the tuple. One-line change.

Document the exclusion in `CONTEXT.md` so it's not invisible.

Theory revision: NULL `installed_at` / UNKNOWN `type` rows are
more consistent with "patch installed via Windows Update or
built-in hotfix mechanism" than "Ninja vs OS". The earlier theory
was directionally right but the precise binary doesn't hold —
operator-confirmed by inspecting individual rows.

### `INGEST_PATCHING_ENABLED_POLICIES` env var

Operator pointed at this in `.env.example`. Likely an allowlist
of Ninja policy IDs so we only ingest patches from devices on
those policies. Could explain large UNKNOWN counts if the ingest
is currently pulling patches for non-patching-enabled devices.

**Implementation status: unverified.** Need to grep the code
(no changes — read-only) to confirm whether the var is actually
wired up or whether it's aspirational config still pending
implementation.

### Side findings

- `ninja_core.devices` has no `needs_reboot` column (the F query
  failed). The column lives on `device_snapshots` instead. Several
  dashboard queries currently read `d.needs_reboot` directly from
  `ninja_core.devices` — those will be returning bogus results.
  **Separate bug worth logging.**
- `earliest install: 2010-11-20` (seen in E2) is suspicious
  — one or two records have malformed installed_at timestamps
  decades in the past. Not blocking but worth a sanity check.


## Hypotheses tracker

- [ ] H1: ingest missed this device's install_outcome rows.
- [ ] H2: install_outcome rows exist but `installed_at` is NULL.
- [ ] H3: install_outcome rows exist but classification CTE
       filters them out (wrong fact_type or status).
- [ ] H4: Activities feed shows non-install events (messages,
       approvals) that the operator is misinterpreting as installs.

## Reference: classification logic (current)

From `last_install` CTE used across CC / Overall / Org / PCOV:

```sql
WITH last_install AS (
    SELECT device_id, MAX(installed_at) AS last_install_at
    FROM ninja_patches.patch_facts
    WHERE fact_type = 'install_outcome'
      AND installed_at IS NOT NULL
    GROUP BY device_id
)
```

A device counts as **never-patched** when there's **no row** in
`last_install` for it — i.e. no `install_outcome` row with a
non-NULL `installed_at`.

## Queries

### Q1 — Recent activities for device 4042

```sql
SELECT
    activity_time,
    activity_type,
    source_name,
    source_type,
    subject,
    LEFT(COALESCE(message, ''), 200) AS message_preview
FROM ninja_activities.activities
WHERE device_id = 4042
ORDER BY activity_time DESC
LIMIT 100;
```

Run with:

```bash
docker exec ninja-postgres psql -U ninja -d ninja -c "
SELECT activity_time, activity_type, source_name, subject,
       LEFT(COALESCE(message, ''), 200) AS message_preview
FROM ninja_activities.activities
WHERE device_id = 4042
ORDER BY activity_time DESC
LIMIT 100;
"
```
