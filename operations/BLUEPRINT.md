# PLAN-004 corrective repair — restricted observation reads

## Goal and scope

Restore the affected Computer UI paths without restoring the Operations
application's direct access to restricted observation payloads. Production
tracebacks on 2026-10-21 confirm that global search and Computer detail read
`entity_observation_current` directly after migration 0117 revoked that
access. The History tab and Hudu-archive finding action contain the same
unsafe read pattern.

Extend the existing reviewed, tenant-filtered, security-barrier metadata
projection with only the scalar identifiers required by those callers. Move
the four user-facing reads to it and add focused regression coverage. Do not
grant the application role the raw table or payload JSON. This repair is
independent of PLAN-012's population design and must preserve PLAN-013's
authentication work.

## Status, validation, and checkpoint

Implementation authorized 2026-10-21. Migration 0334 extends
`v_entity_observation_admin_metadata`; Computer name provenance, global
search, History, and Hudu-archive eligibility now use it. The raw table
remains denied to runtime readers; the two remaining references in `views.py`
are intentional guarded updates.

`ruff check` passed for the migration and focused tests; Python compilation,
registry validation, and `git diff --check` passed. Django/pytest are absent
from the workstation interpreter. Docker Compose could not run the focused
tests because its Operations container requires the unavailable local database
password; it created an empty local Compose network and volume only. No
production schema or application state has changed. Commit and deployment
push were approved on 2026-10-21. Next action: commit this repair, push it,
then verify the deployed endpoints and migration under the runtime role.

# PLAN-013 — Operations sign-in page

## Goal

Let any active Operations user sign in without Django admin staff status.
Permissions continue to come from groups (`viewer`, `operator`, `admin`).

## Scope

- `/login/`, `/logout/` (POST), and `/account/password/` change-password
  pages using Django's built-in auth views; no new dependency, model,
  migration, or permission change.
- `LOGIN_URL` points at `/login/`; header sign-in/sign-out links use the new
  pages. `/admin/login/` remains available for staff.
- Out of scope: SSO (Entra/OIDC), an Operations Users page, and the existing
  `is_staff` checks that gate editing on Finding types, Software policy,
  client mappings, Home system links, and Sources.

## Affected files

`config/settings/base.py`, `config/urls.py`, `templates/base.html`,
`templates/registration/login.html`,
`templates/registration/password_change_form.html`,
`templates/registration/password_change_done.html`,
`apps/core/tests/test_login.py`.

## Decisions

- Built-in `LoginView`/`LogoutView`/`PasswordChangeView`: the views run after
  `TenantMiddleware`, so the user lookup happens under the tenant GUC and RLS.
- Logout becomes a POST form. Django 5 rejects GET logout, so the previous
  header link to `admin:logout` returned 405.
- Staff status stays the gate for `/admin/` and for the existing `is_staff`
  edit checks; changing those is a separate authorization decision.

## Status

Implemented and validated locally; committed and pushed on user approval (2026-10-21). Deployed-stack sign-in not yet verified.

## Validation

- `pytest apps/core/tests/test_login.py`: 6 passed (sign-in render, POST-only
  sign-out, password change requires sign-in, header links, templates).
- Full `pytest apps`: 439 passed, 133 skipped, 4 failed; the same 4
  conditions/generic-admin failures occur on clean HEAD 3091a47.
- `manage.py check` clean; ruff check/format clean on new files. Pre-existing
  format drift in `config/urls.py` and `config/settings/base.py` left as is.
- Not validated: a real database sign-in (local settings use the SQLite
  skeleton) and the deployed stack.

## Checkpoint

Committed. Follow-ups (group-based edit checks, SSO decision, Users page)
are in `operations/TODO.md`.

## Next action

Verify sign-in, sign-out, and password change on the deployed stack, then mark PLAN-013 complete.
