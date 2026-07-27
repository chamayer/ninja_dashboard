# Operations UI Redesign — All 4 Tracks

**Status:** COMPLETE — all 4 tracks done, awaiting visual smoke pass + release approval
**Goal:** Consistent, operator-friendly UI across all sections — no jargon, uniform layout primitives, functional nav, durable enough to not need a redo
**Scope:** Templates + context_processors.py only. No model changes, no URL changes, no view logic changes.

---

## Track 1 — CSS primitives + tile/font uniformity

**Goal:** Every stat tile, table, and filter bar in every section uses the same base class. One spec for numbers.

### Tile unified spec

Current problem — sizes used across the codebase:
- `.sw-tile .sw-value`: 1.6rem/700 (software overview)
- `.patch-status-card .value`: 1.45rem/700 (patching)
- `.tc-tile .value`, `.ur-tile .value`: 1.35rem/600
- `.sw-week-item .v`: 1.25rem/700
- base.html `.tile-value`: 1.6rem/**600** — fix to 700

Canonical spec (all in base.html):
- `.tile-grid`: repeat(auto-fill, minmax(180px,1fr)), gap 0.65rem
- `.tile`: surface bg, border, radius 6px, padding 0.85rem 1rem, block, transition
- `.tile:hover`: border-color accent
- `.tile-good/.tile-warn/.tile-alert`: left-border 3px (green/orange/red)
- `.tile-label`: 0.72rem, 700, uppercase, letter-spacing 0.05em, var(--muted)
- `.tile-value`: 1.6rem, 700, #1a1a2e, line-height 1.1, margin-top 0.2rem
- `.tile-note`: 0.75rem, var(--muted), margin-top 0.2rem
- `.tile-value.alert`: color #b45309 (amber for "has open items")

### Migration map

| Template | Remove classes | Replace with |
|---|---|---|
| base.html | fix `.tile-value` weight 600→700; add `.tile-note`, `.tile-good/warn/alert` | — |
| software_page.html | `.sw-numbers`, `.sw-tile`, `.sw-label`, `.sw-value`, `.sw-sub`; `.sw-week-item .k/.v/.sub` | `.tile-grid`, `.tile`, `.tile-label`, `.tile-value`, `.tile-note` |
| patching_queue.html | `.patch-status-grid`, `.patch-status-card`, `.label`, `.value`, `.sub`, `.good/.warn/.alert` | `.tile-grid`, `.tile.*` unified |
| software_tech_checklist.html | `.tc-tiles`, `.tc-tile` + local label/value | `.tile-grid`, `.tile` |
| software_user_risk.html | `.ur-tiles`, `.ur-tile` + local label/value | `.tile-grid`, `.tile` |
| devices_page.html | `.dv-tile`, `.dv-label`, `.dv-value`, `.dv-sub` | `.tile.*` unified |
| patch_trends.html | `.pt-tiles`, `.pt-tile` | `.tile-grid`, `.tile` |
| patch_evidence.html | `.pe-status-tiles`, `.pe-tile` | `.tile-grid`, `.tile` |
| coverage.html | `.cov-tiles`, `.cov-tile`, `.tl`, `.tv`, `.ts` | `.tile-grid`, `.tile` |
| findings_queue.html | `.tile-row`, `.sev-tile`, `.sev-label`, `.sev-count` | `.tile-grid`, `.tile` |

### Tables

base.html `.ops-table` is the canonical class. Migrate:
- `software_page.html` `.sw-table` → `.ops-table`
- `patching_queue.html` `.patch-posture-table` → `.ops-table`
- `patch_activity.html` `.pa-table` → `.ops-table`
- `patch_trends.html` `.pt-table` → `.ops-table`
- `patch_evidence.html` `.pe-table` → `.ops-table`
- `_sw_style.html` `.sw-table` → `.ops-table` (affects products/publishers/decisions/log)

### Filter bars

base.html `.filterbar` is the canonical class. Migrate:
- `_sw_style.html` `.sw-filterbar` → remove; templates use `.filterbar`

---

## Track 2 — Terminology pass

| Find (exact) | Replace with | File(s) |
|---|---|---|
| "Whitelist suggestions" | "Allow-list candidates" | software_page.html |
| "Unclassified" (KPI tile label) | "Not categorized" | software_page.html |
| `lastLoggedInUser` | "last logged-in user" | software_user_risk.html |
| "e.g. suspicious_name" | "e.g. suspicious name" | software_tech_checklist.html, software_user_risk.html |
| "User risk" (page title h1) | "User exposure" | software_user_risk.html |
| "Per-user rollup of software checklist items on the device that user last logged into. Uses Ninja's `lastLoggedInUser` (latest per device); a user who logs into multiple devices is aggregated across all of them." | "Software items flagged on the last device each user logged into. Users who use multiple devices are shown across all of them." | software_user_risk.html |
| patch_trends: "Per-day install / failure volumes from ninja_patches.patch_facts" | "Daily install and failure counts from Ninja patch data." | patch_trends.html |
| patch_evidence: "Replaces the legacy patching CSV report and the Metabase Patch Evidence dashboard" | remove sentence | patch_evidence.html |
| coverage page h1 "Compliance" | "Coverage" | coverage.html |
| sources: "Ingest status per source platform" | "Connection status by data source" | sources.html |
| sources: "stale source" chip label | "Stale" | sources.html |
| patch activity: "Recent patch install outcomes collected from Ninja. Each row retains Ninja's event time, collection time, original evidence payload. Newest first, capped at 500 rows per query." | "Recent patch install results from Ninja, newest first." | patch_activity.html |
| "Cleanup by device" (wf-card) | "Device cleanup queue" | software_page.html |
| "User exposure" wf-card desc "who is exposed to risky software — grouped by last-logged-in user" | "Risky software grouped by the user who last logged in" | software_page.html |
| software_tech_checklist desc paragraph | "Per-device software cleanup queue. Combines classifier findings with operator block/review decisions — the list a technician works through." | software_tech_checklist.html |

---

## Track 3 — Nav overhaul

### context_processors.py — add `active_section`

```python
url_name = getattr(getattr(request, 'resolver_match', None), 'url_name', '') or ''
if url_name == 'home':
    section = 'home'
elif any(x in url_name for x in ('software',)):
    section = 'software'
elif any(x in url_name for x in ('patch',)):
    section = 'patching'
elif url_name in ('devices_page', 'device_detail', 'device_merge', 'org_devices'):
    section = 'devices'
elif 'finding' in url_name:
    section = 'issues'
elif 'org' in url_name or 'client' in url_name:
    section = 'clients'
else:
    section = ''
ctx['active_section'] = section
```

Note: admin pages set `admin_group` in view context; treat `admin_group` truthiness as "admin section" in base.html (already working).

### base.html primary nav — fix active states

Replace fragile `request.resolver_match.url_name == 'x'` checks with `active_section`.

### base.html Row 3 — section sub-nav

Add elif branches:
- `active_section == 'software'` (and no `current_client`, no `admin_group`): show software sub-tabs inline
- `active_section == 'patching'` (and no `current_client`, no `admin_group`): show patching sub-tabs
- Admin: extend existing `admin_group` branch to show sub-tabs for the active group inline

**Software sub-tabs:** Overview | Products | Publishers | Cleanup | User exposure | Activity

**Patching sub-tabs:** Summary | Evidence | Trends | Activity

**Admin sub-tabs (per group):**
- review: Clients · Merges · Software decisions
- config: Alerts · Suppressions · Requirements · Classifier · Device status
- integrations: Sources · Coverage · Ingest · Jobs

### Templates to update

- Remove `{% include "_software_tabs.html" %}` from all software templates
- Remove inline Evidence/Trends/Activity links from patching_queue.html header
- Remove `{% include "_admin_tabs.html" %}` from all 11 admin templates

---

## Track 4 — Section layout

### Patching

- Replace mixed card-header + inline links with consistent `.page-header` div (h1 + muted description)
- Remove inline style attrs from h2 elements; use `class="section-label"` pattern

### Devices

- Add proper page-header section
- Unify tile grid

### Software sub-pages (tech checklist, user risk)

- `.tc-header` / `.ur-header` → convert to `.page-header` pattern matching rest of software section

### Issues / Findings

- Convert `.sev-tile` tiles to unified `.tile`

### Home

- Rationalize: keep bespoke layout for now (it is the most complex); clean up font sizes and ensure section labels are consistent

---

## Checkpoint

- [x] Track 1 — CSS primitives + tiles (base.html + all templates)
- [x] Track 2 — Terminology
- [x] Track 3 — Nav (context_processors + base.html + template include removal)
- [x] Track 4 — Layout
- [x] `python manage.py check` — 6 security warnings only, 0 errors
- [ ] Template smoke pass
- [ ] VERSION + CHANGELOG (when approved for release)
