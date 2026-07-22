# Active Operations work plan

Track: **Client service requirements and profile overrides**

## Status

- Complete. Requirement profiles are reusable baselines with explicit
  per-client service overrides and an operator-facing configuration page.

## Goal

Let an operator independently require, exempt, or inherit each supported
service for a client, without cloning a profile for every service combination.

## Scope

- **In:** evaluator requirement precedence, client configuration UI, audit,
  tests, and architecture documentation.
- **Out:** changing connector/source configuration, source-link mapping, or
  finding severity semantics beyond an existing client override.

## Affected files

- `../ingest/evaluator.py`
- `apps/core/views.py`, `config/urls.py`
- `templates/client_requirements_config.html`, `templates/org_index.html`
- tests and `docs/architecture.md`
- `.work/plan.md`

## Decisions

- `RequirementProfile` remains a reusable baseline. A profile never appears as
  the client name or primary dashboard identity.
- Client-scoped `CoverageRequirement` rows are sparse overrides: enabled means
  explicitly required, disabled means explicitly not required, and no row means
  inherit.
- Effective precedence is: client override → assigned profile → tenant-global
  fallback. Overrides use the existing agent and device-scope semantics, not a
  new source-policy model.
- The client UI calls an `Agent` a service because that is understandable to an
  operator; the evaluator remains agent-backed for OS compatibility and
  thresholds.

## Steps

- [x] Add override-aware effective-requirement resolution to the evaluator and
  auto-resolution path.
- [x] Add an audited per-client service-requirements configuration page.
- [x] Link the client dashboard Configuration card to the new page.
- [x] Add focused tests and update architecture documentation.
- [x] Validate and review the migration-free deployment path.

## Validation plan

- Unit-test precedence, including explicit required and explicit not-required
  overrides over a profile baseline.
- Run targeted tests, `python manage.py check`, Ruff, and `git diff --check`.

## Checkpoint

- Current evaluator treats an assigned profile as complete truth and ignores
  client-scoped `CoverageRequirement` rows. The table already contains the
  `client_id`, `agent_id`, scope, thresholds, and enabled state needed for
  sparse overrides; the missing work is precedence and UI.
- Other-agent edits are present in `../ingest/core/devices.py`,
  `apps/core/views.py`, and `templates/device_detail.html`. They are unrelated
  raw-snapshot work and must remain intact.
- The evaluator now applies `all` overrides before device-role overrides;
  enabled rows add or replace requirements and disabled rows remove inherited
  requirements. Auto-resolution applies the same disabled/explicit-required
  semantics, so stale coverage findings close when a service becomes exempt.
- Validation: `makemigrations --check --dry-run` reports no changes,
  `python manage.py check` passes, focused tests pass (11), URL reversal and
  template loading pass, import/format checks for changed standalone files and
  `git diff --check` pass. Broad Ruff output still contains pre-existing
  complexity/style findings in `evaluator.py` and other unrelated views.

## Next action

- Deploy and verify an explicit required and not-required override against a
  test client before applying broader client configuration changes.
