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
