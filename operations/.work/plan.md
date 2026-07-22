# Active Operations work plan

Track: **Device-status policy and source-state configuration**

## Status

- In progress.

## Goal

Replace hidden device-status policy thresholds with an explicit tenant-wide
admin surface, and ensure online status reflects the latest source-reported
state rather than an inferred contact-age window.

## Scope

- Operations configuration/UI, shared device-status policy readers, Patching
  evaluator consumption, and the derived current session view migration.

## Decisions

- **Active device** means a non-retired device has contacted a source within
  the tenant policy's active-device window (seven days by default). It is
  shared across Dashboard, Clients, Devices, coverage drill-downs, and
  Patching, and is distinct from `online now`.
- **In patching scope** is a policy decision, not activity.
- **Recent patch activity** means a Ninja patch scan/state observation or
  install outcome within the existing 35-day stalled-patching window.
- Status cards use explicit denominators and drill into the devices behind the
  measure. Exception findings remain supporting detail, not the page framing.
- Ninja patch facts are evidence. Show their event time, collection time,
  patch state/outcome, and the collected payload where present; never imply a
  payload field was normalized when it was merely collected raw.
- **Online now** is the latest source-reported online state. Contact age is
  displayed separately as freshness and never silently turns an old record
  into "offline".
- Operational thresholds are tenant-wide to preserve portfolio comparability.

## Steps

- [x] Identify policy thresholds and distinguish guardrails from configurable
  operational policy.
- [x] Add the Device status & patching admin UI using `EvaluatorConfig`.
- [x] Make Operations and the patch-finding evaluator read the tenant policy.
- [x] Migrate session state to retain latest source-reported online state.
- [ ] Validate migration SQL, policy defaults, templates, and affected tests.

## Validation plan

- Django system check, template loading, targeted patching tests where present,
  Ruff/format checks for changed Python, and `git diff --check`.

## Validation

- `python -m compileall` on changed Operations and ingest Python — pass.
- `python manage.py check` — pass.
- `pytest apps/core/tests -q` — 23 passed.
- `python manage.py makemigrations --check --dry-run` — no changes detected.
- `python manage.py sqlmigrate operations 0077` — rendered successfully.
- Focused Ruff checks and `git diff --check` — pass.
- Local Django settings have no database engine, so migration `0077` has not
  been executed against a PostgreSQL instance from this workstation.

## Checkpoint

- Commit `953955b` shipped the Patching overview and the initial shared
  seven-day active-device definition.
- The audit found active (7d), online inference (24h), patch stalled (35d),
  reboot pending (3d), repeated failures (3), approval backlog (25), and
  source delay (8h) as operational thresholds. They are now tenant policy;
  page/CSV caps remain technical guardrails.
- Migration `0077` recreates current presence/session readers so online uses
  the latest explicit `is_online`/`offline` source value (or VM power state),
  with freshness retained as a separate timestamp.

## Next action

- Run the final validation and commit the policy/UI, evaluator, and session
  projection work while preserving the unrelated `org_index.html` worktree
  change.
