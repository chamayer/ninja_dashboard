# Current Task Blueprint

> Per `Development/DEVELOPMENT.md` Agent Work Rule #5. Overwritten
> per task. Historical record lives in `SESSIONS.md` and `CHANGELOG.md`.

---

## Goal

Fix two issues surfaced in the device-4042 troubleshooting session
(see `TROUBLESHOOTING.md`):

1. **Never-Patched misclassification**: 6 devices fleet-wide are
   classified as never-patched because every `install_outcome /
   INSTALLED` row they have has a NULL `installed_at`. Device 4042
   is one of them.
2. **Patch category invisibility**: `patch_facts.type` (Ninja's
   category: `SECURITY_UPDATES`, `DRIVER_UPDATES`, etc.) is stored
   but never surfaced. Operator wants it visible on patch tables,
   plus an env-driven exclude so `DRIVER_UPDATES` can be hidden
   everywhere until they're in scope.

## Why

- **Never-Patched bug** misleads the operator into investigating
  healthy devices. Root cause confirmed: Ninja's
  `/queries/os-patch-installs` omits `installedAt` for historical /
  OS-applied patches (~1.2 % of all INSTALLED rows). The
  `ninja_patches.device_patch_signal` materialized view filters
  `installed_at IS NOT NULL`, so devices whose only INSTALLED rows
  lack a timestamp disappear from the signal table → classified as
  never-patched.
- **Why not use `ninja_observed_at` as a fallback install date:**
  it's Ninja's *scan timestamp*, refreshed every ingest cycle
  (`update_cols=["...", "ninja_observed_at", ...]` in
  `ingest/patches/ingest.py:128`). Using it as a proxy for install
  time would silently classify "device that Ninja keeps re-scanning
  ancient installs on" as *actively patching* — replacing one
  misclassification with another. The honest answer for those rows
  is: install existed at some point, install date is unknown.
- **Category surfacing**: 70 % of pending patches are
  `DRIVER_UPDATES`. Operator isn't installing drivers (yet) and
  doesn't want them polluting `Manual approvals waiting`,
  `Pending patches by severity`, Patch Detail tables, etc. Visible
  `Type` column closes the "what is this row?" gap when drivers
  come back in scope.

## Scope

**In:**
- Migration `016_*.sql`:
  - Rebuilds `device_patch_signal` to expose `ever_installed`
    (existence-only bool) alongside the existing `last_install_at`
    (still strictly `MAX(installed_at)`). Drops the `WHERE
    installed_at IS NOT NULL` filter on the underlying scan so the
    bool can be set for date-less devices.
  - Adds `patch_category` (sourced from `pf.type`) to
    `latest_install_outcome` and `current_patch_state`. ORDER BY
    of `latest_install_outcome` unchanged (confirmed in Q3 of the
    prior blueprint discussion).
- New env var `DASHBOARD_PATCH_CATEGORIES_EXCLUDE` (default
  `DRIVER_UPDATES`). Read at bootstrap time, rendered into a
  shared `_PATCH_TYPE_EXCLUDE` predicate fragment, appended to
  every patch-context query's WHERE.
- Add `Type` column to operator-facing patch list cards (Manual
  approvals, Pending by severity, Patch Detail tables, Device
  Drilldown patch tables).
- Update `CONTEXT.md` to document the new env var and the
  `effective_installed_at` fallback rule.

**Out / separate:**
- `ninja_core.devices.needs_reboot` bug (column missing, several
  cards read it directly — logged in `TROUBLESHOOTING.md` side
  findings). Note: `v_active_devices` (migration 015) DOES expose
  `needs_reboot` correctly, so cards that reference
  `d.needs_reboot` when `d` is `v_active_devices` are fine. Only
  cards joining `ninja_core.devices` directly are broken.
- 2010-11-20 outlier `installed_at` value — separate sanity check.
- Patch-Category dashboard FILTER (operator explicitly said no —
  surface only).
- `INGEST_PATCHING_ENABLED_POLICIES` audit — separate task.
- **Dead code cleanup**: `_PATCH_SCOPE_CTE` (line 224 of
  `metabase_bootstrap.py`) is defined but never referenced — the
  scope work moved into `v_active_devices` in migration 015 and
  every card now filters off `d.patching_scope` directly. Worth
  deleting in a future cleanup pass; not in this task to keep the
  diff focused.

## Files to change

- `sql/migrations/016_install_signal_coalesce_and_category.sql`
  (new) — rebuild the three materialized views.
- `ingest/config.py` — add `dashboard_patch_categories_exclude`
  setting (default `("DRIVER_UPDATES",)`).
- `.env.example` — document the new var.
- `ingest/metabase_bootstrap.py`:
  - New module-level constant + `_PATCH_TYPE_EXCLUDE` fragment
    rendered from `settings.dashboard_patch_categories_exclude`.
  - Append the fragment to `_COMPLIANCE_CTES` source CTEs
    (`installed_patches`, `missing_patches`) and to every other
    patch-context CTE that reads from `latest_install_outcome`,
    `current_patch_state`, or `patch_facts` directly. (Grep
    targets: lines that mention `fact_type = 'install_outcome'`,
    `fact_type = 'patch_state'`, `current_patch_state`,
    `latest_install_outcome`.)
  - Add `cps.patch_category` / `lio.patch_category` to the
    `SELECT` lists of operator-facing patch tables. At minimum:
    Manual approvals, Pending by severity tables, Patch Detail
    list, Device Drilldown patch tables.
- `CONTEXT.md` — append "Patch category exclusion" subsection
  near the existing Compliance formula block.
- `CHANGELOG.md` + `VERSION` bump (likely 0.14.12 → 0.15.0 since
  it's a behavior change to compliance counts).
- `TROUBLESHOOTING.md` — mark resolved sections; archive into
  `SESSIONS.md`.

## Steps

1. **Write migration 016.** Dependency order matters:
   `device_troubleshooting_signal` (migration 015 — supersedes
   014) reads from both `current_patch_state` and
   `latest_install_outcome`, so it must be dropped first.
   Sequence:
   ```
   DROP MV device_troubleshooting_signal
   DROP MV device_patch_signal
   DROP MV latest_install_outcome
   DROP MV current_patch_state
   -- recreate in reverse order:
   CREATE MV current_patch_state    (+ patch_category column)
   CREATE MV latest_install_outcome (+ patch_category column)
   CREATE MV device_patch_signal    (+ ever_installed column;
                                       last_seen_at column NAME
                                       UNCHANGED but stops
                                       filtering NULLs at source)
   CREATE MV device_troubleshooting_signal (logic updates below)
   ```
   - `device_patch_signal` — **keep column name `last_seen_at`**
     to avoid renaming a symbol referenced 53× in
     `metabase_bootstrap.py`. Definition becomes:
     ```sql
     SELECT
         device_id,
         BOOL_OR(status = 'INSTALLED') AS ever_installed,
         MAX(installed_at) AS last_seen_at,  -- only real install
                                              -- dates; NULL when
                                              -- ever_installed AND
                                              -- no dates known
         COUNT(*) FILTER (WHERE installed_at IS NOT NULL)
             AS install_attempts
     FROM ninja_patches.patch_facts
     WHERE fact_type = 'install_outcome'
     GROUP BY device_id;
     ```
     Same column shape as today + one new bool. All existing
     `dps.last_seen_at` references continue to work; meaning is
     preserved (strict last real install date).
   - `latest_install_outcome` — add `patch_category` column
     (sourced from `pf.type`). ORDER BY unchanged.
   - `current_patch_state` — add `patch_category` column.
   - `device_troubleshooting_signal` — duplicate migration 015's
     definition verbatim with three changes:
     a) `LEFT JOIN device_patch_signal dps` block now also reads
        `dps.ever_installed`.
     b) `patch_status` CASE: replace
        `WHEN dps.last_seen_at IS NULL THEN 'no_patch_data'` with
        `WHEN NOT COALESCE(dps.ever_installed, FALSE) THEN
         'no_patch_data'`. The other two branches unchanged
        (NULL `last_seen_at` will naturally fall through to
        `stale_patch_data` since NULL < anything-with-NOW() — but
        explicit branch wins on clarity, see (c)).
     c) `issue_type` CASE: same swap (`NOT
        COALESCE(dps.ever_installed, FALSE)` for the
        `'Never patched'` branches). Add a new branch ABOVE the
        generic `'Stalled'` fallback:
        ```sql
        WHEN dps.last_seen_at IS NULL
            THEN 'Stalled (install dates missing)'
        ```
        and matching `suggested_action`:
        `'Ninja reports installs but without dates — verify agent
         patch reporting'`.
2. **Wire the env var.**
   - `ingest/config.py`: parse `DASHBOARD_PATCH_CATEGORIES_EXCLUDE`
     (comma-separated, stripped, tuple). Default
     `("DRIVER_UPDATES",)`.
   - `.env.example`: add the var with comment listing all known
     Ninja categories.
3. **Render `_PATCH_TYPE_EXCLUDE`** at top of
   `metabase_bootstrap.py`, near `COMPLIANCE_MISSING_SQL`. Empty
   string when the tuple is empty.
4. **Apply the fragment** to every patch-context CTE / SELECT
   that touches `patch_facts`, `current_patch_state`, or
   `latest_install_outcome`. Pattern:
   ```python
   _PATCH_TYPE_EXCLUDE = (
       "  AND COALESCE(patch_category, 'UNKNOWN') NOT IN ({})\n".format(
           ", ".join(f"'{t}'" for t in settings.dashboard_patch_categories_exclude)
       )
       if settings.dashboard_patch_categories_exclude else ""
   )
   ```
   Note: `'UNKNOWN'` coalesce is a no-op (UNKNOWN isn't in the
   default exclude list) but defends against NULL category rows
   slipping through if Ninja ever returns one.
5. **Surface `Type` column** on operator patch tables. Single new
   column per table; no extra logic. Place between `KB` /
   `Severity` and `Patch Name`.
6. **Refresh logic — verified, no code change needed.** Refresh
   calls already exist:
   - `ingest/patches/ingest.py:135-137` refreshes the three patch
     MVs after writes (current_patch_state, latest_install_outcome,
     device_patch_signal).
   - `ingest/summary_views.py:18` refreshes
     `device_troubleshooting_signal` (cross-domain rollup that
     reads patch MVs + activity signal + latest_device_health).
   - `main.py` orchestration order must keep summary refresh AFTER
     patches+activities+health refreshes. Existing order assumed
     correct; quick verify in step 8 smoke test.
   - All refreshes are full `REFRESH MATERIALIZED VIEW` (not
     `REFRESH ... CONCURRENTLY`) → brief lock during refresh, OK
     at hourly cadence. Not in scope to change.
7. **Update classification logic in `metabase_bootstrap.py`.**
   Every place that currently reads `dps.last_seen_at IS NULL` to
   mean "never patched" must switch to `dps.ever_installed IS NOT
   TRUE`. Devices with installs-but-no-dates fall into **Stalled**
   alongside genuinely stalled devices — same operator action
   needed (investigate), no new bucket, no dashboard rewrites:
   - `ever_installed = FALSE` (or no row) → **Never patched**
   - `ever_installed AND (last_install_at IS NULL OR
     last_install_at < now() - 35d)` → **Stalled**
   - `ever_installed AND last_install_at >= now() - 35d` →
     **Actively patching**

   Same condition swap in `device_troubleshooting_signal`
   (migration 014). Add ONE new `issue_type` discriminator inside
   the existing Stalled tree for the dateless case so the operator
   sees why these devices landed there:
   ```sql
   WHEN dps.ever_installed AND dps.last_install_at IS NULL
       THEN 'Stalled (install dates missing)'
   ```
   with `suggested_action` like `'Ninja reports installs but
   without dates — verify agent patch reporting'`. Place this
   branch BEFORE the generic `last_install_at < now() - 35d`
   stalled branches (NULL won't match `<` anyway, but explicit
   ordering keeps it readable).

   Document the rule in `CONTEXT.md` near the patch status
   glossary: "Devices whose only INSTALLED rows lack
   `installed_at` (Ninja's API omits the field for some historical
   / OS-applied patches) are bucketed as Stalled, not Never
   patched. ~6 devices fleet-wide today."
8. **Compile + smoke test.**
   - `python -m py_compile ingest/metabase_bootstrap.py`.
   - Local Postgres: apply 016, refresh MVs, spot-check:
     - Device 4042 row in `device_patch_signal`: `ever_installed =
       true`, `last_install_at IS NULL`.
     - Compliance scalar reclassifies 4042 out of *Never patched*
       into *Stalled*, with `issue_type = 'Stalled (install dates
       missing)'`.
     - `SELECT COUNT(*) FROM device_patch_signal WHERE
       ever_installed AND last_install_at IS NULL;` → ~6 (the
       previously-misclassified set, now in Stalled).
     - Driver-exclude check: representative Metabase card SQL run
       manually returns zero driver rows.
9. **Doc + commit.**
   - Update `CONTEXT.md` (new bucket, env var, classification rules).
   - Update `CHANGELOG.md` + `VERSION`.
   - Migrate the relevant `TROUBLESHOOTING.md` sections into a
     `SESSIONS.md` entry, then trim `TROUBLESHOOTING.md` to the
     remaining open items (needs_reboot column, 2010 outlier,
     INGEST_PATCHING_ENABLED_POLICIES audit).
10. **Commit + push after approval.** Report commit hash per the
    commit-hash-after-push rule.

## Open questions

- Bump to **0.14.12** (patch) or **0.15.0** (minor)? Recommend
  **0.14.12** now that the change is scoped to a classification
  swap + env var. No new bucket, no card rewrites.
- `issue_type` label for the dateless-stalled case: `'Stalled
  (install dates missing)'` — open to a shorter phrasing.

## Status

done — pending real-DB smoke test on next ingest cycle and commit
