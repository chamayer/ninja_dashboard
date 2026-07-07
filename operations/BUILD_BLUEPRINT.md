# Goal

Validate the committed Operations container in the Portainer-managed
`ninja-dashboard` stack, then choose the next M1 implementation slice.

# Why

The repository is ahead of the previous checkpoint docs. M0.11/M0.12 and
several M1 UI/data slices are already committed and pushed:

- `f13fc9b` — bootstrap clients from `ninja_core.organizations` (M0.11).
- `aab87da` — brand context, base template, client selector (M0.12).
- `afee1bf` — bootstrap devices from `ninja_core.devices` (M1.1).
- `c32dae5` — per-client device list, device detail, external identities.
- `45c1334` — findings queue landing page.
- `c1f6f9f` — all-clients fleet view and merge candidates queue.
- `f1e7fab` — client policy editor.
- `4ffc73a` / `0e2185b` / `25584a0` — summary hub/sub-pages and
  `device_kind` → `device_type` cleanup.
- `746770e` — admin sessions survive same-password redeploys.

The next useful checkpoint is live container validation, because local Docker
is unavailable on this workstation and the blueprint's deployment target is
Portainer on `am-ch-01`.

# Scope

In:

- Verify the Operations service builds and starts through the existing
  `ninja-dashboard` Portainer stack.
- Confirm startup migrations run as `operations_migrate` and runtime Gunicorn
  uses `operations_app`.
- Confirm `/healthz` responds on `127.0.0.1:8091`.
- Confirm `bootstrap_clients_from_ninja` and `bootstrap_devices_from_ninja`
  populate Operations from the existing Ninja schemas.
- Confirm an existing admin session survives a same-password redeploy.
- Record validation results in `operations/SESSIONS.md` and `operations/TODO.md`.

Out:

- New UI pages or UI polish.
- New schema migrations.
- New ingest/classification behavior.
- TLS/reverse-proxy work, which remains backlog.
- CI/pre-commit restoration, which is deferred until the existing lint debt is
  intentionally addressed.

# Files to change

- `operations/BUILD_BLUEPRINT.md` — active checkpoint and next-step status.
- `operations/TODO.md` — completed/pending state cleanup.
- `operations/SESSIONS.md` — validation result once live checks complete.
- No application code for this checkpoint unless validation exposes a defect.

# Steps

1. On `am-ch-01`, verify the pushed commit is available to Portainer:
   `746770e`.
2. Redeploy the existing `ninja-dashboard` stack with the Operations service.
3. Check `ninja-operations` logs for successful migrate/bootstrap/startup.
4. Run `curl -fsS http://127.0.0.1:8091/healthz` on the host.
5. Check Django migrations with `docker exec -it ninja-operations python
   manage.py showmigrations`.
6. Spot-check Operations data counts for clients, client links, devices, and
   device links.
7. Keep an existing admin browser session open, redeploy once more with the
   same `OPERATIONS_INITIAL_ADMIN_PASSWORD`, and confirm the session remains
   logged in.
8. Record the live validation outcome and then select the next M1 slice.

# Open questions

- Which remote/branch Portainer is configured to pull for this stack if both
  `origin` and `a-m-rose` are present.
- Whether the live `.env` already has all required Operations keys and role
  passwords.
- Whether to fix existing Ruff debt next or continue product M1 features.

# Status

Docs reconciled to committed state. Awaiting live Portainer validation before
starting another implementation slice.
