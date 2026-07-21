# Active root work plan

Track: **Legacy agent-compliance refresh bridge**

## Status

- In progress — repairing the legacy ingestion path while Operations remains the
  planned replacement.

## Goal

Restore reliable legacy agent-compliance refreshes without coupling the legacy
schema to the new Operations data model.

## Scope

- In: normalization of incomplete legacy source observations; focused tests,
  safe validation of the collection path, repair of organization-only rows,
  and correcting the deployment-remote documentation.
- Out: legacy-schema migration, changes to Operations ownership, alert-policy
  changes, cutover/decommissioning, deployment, commit, and push.

## Files involved

- `ingest/agent_compliance/ingest.py` — legacy collection and persistence.
- `ingest/tests/` — focused regression coverage if applicable.
- `operations/.work/plan.md` — pointer to this cross-service work.
- `AGENTS.md`, `docs/operations.md` — deployment remote authority and mirror
  procedure.

## Steps

- [x] Diagnose the live refresh failure.
- [x] Determine valid fallback semantics for source rows without a device type.
- [x] Implement the smallest legacy-only normalization; this ingest package has
  no test suite/configuration, so validation will use focused compilation and
  a mocked database call.
- [x] Run focused validation and review the diff.
- [x] Commit the repair and push it to the secondary mirror.
- [ ] Push the repair to deployment authority (`origin`) and verify GitOps
  deploys it before the live refresh.
- [ ] Repair the organization-only observation insertion exposed by live
  validation, then repeat approval/commit/deploy/refresh validation.
- [ ] Normalize unknown device roles before both legacy persistence and matrix
  construction, as exposed by the second live validation.
- [ ] Commit and push the deployment-documentation correction to both remotes.

## Decisions

- Keep the repair within the legacy ingest bridge: Operations remains
  independent and continues to consume its native derived state.
- Do not invent a device classification until the existing schema constraints,
  historic values, and requirement matching behavior have been verified.

## Validation

- Focused legacy ingestion test.
- Relevant Python lint/format checks when the project environment supports
  them.
- `git diff --check`.
- Live collection verification only after explicit approval of its alert
  behavior and deployment.

## Current checkpoint

- Deployed legacy collection is enabled but the last successful matrix refresh
  was 2026-07-20 20:10 UTC.
- A manually requested collection on 2026-07-21 fetched all four sources, then
  failed inserting a LogMeIn observation with a null `device_type` into the
  non-null legacy `platform_observations.device_type` column.
- The schema's explicit default is `unknown`; `infer_device_role` intentionally
  returns `None` for an unclassifiable role. The ingestion bridge now converts
  that explicit null to `unknown`, allowing the existing `all` scope fallback
  to apply without guessing a device role.
- Focused syntax parsing and an isolated mocked-cursor exercise pass; it proves
  the inserted copy is normalized while the fetched source row is unchanged.
- `git diff --check` passes. The local Python environment lacks the ingest
  runtime dependencies (`httpx`, `pydantic`) and cannot write the parent
  repository bytecode/cache directories, so package import and Ruff checks
  could not be completed here. Ruff also reports two pre-existing whole-file
  findings and format drift outside this change.
- Commit `3cc482a` contains the repair and was first pushed only to the
  secondary `a-m-rose` remote because the local branch tracks it. `origin`
  (`chamayer`) is Portainer's deployment authority and must receive the same
  commit before validation; the documented push order is being corrected.
- Live validation of `3cc482a` proved the null-role repair passes. It then
  revealed a separate pre-existing defect: SentinelOne organization-only rows
  are needed for client synchronization but lack the non-null device columns
  required by `platform_observations`. Keep them for synchronization and omit
  them only from the device-observation persistence/matrix path.
- Live validation of `8bad044` completed all four source writes, but matrix
  persistence still received the original in-memory null role. The
  normalization was only applied to an insert copy; it must instead run before
  both persistence and matrix construction.

## Next action

- Validate the shared role-normalization repair, then request approval for its
  separate commit, push to both remotes, deployment, and another live refresh.
