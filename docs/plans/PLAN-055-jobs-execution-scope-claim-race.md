# PLAN-055 — Jobs execution-scope claim race

## Goal and scope

Prevent the Jobs dispatcher from starting a queued successor while an earlier
run with the same tenant, job definition and scope is still active. Preserve
intentional queued successors and ensure they become claimable after the active
run completes. Keep the existing resource-capacity and workflow dependency
rules intact.

This is a cross-service database/ingest change. It does not alter Computer
ownership semantics or the tenant findings guard.

## Confirmed evidence

On 2026-11-05, production's Jobs worker exited once with a unique violation on
`jobs_one_executing_run` while claiming `computer-client-ownership` for
`tenant:1`. The worker restarted and the queued ownership successor completed.
The claim path is `jobs_claim_next_v7` for source refresh and
`jobs_claim_next_v6` for other definitions. The v6 function selects and locks a
queued row before checking whether an active run already owns that execution
scope. `jobs_request` permits a queued successor while another run is active.

## Design decision

Keep the existing unique indexes and admission path. Both claim functions
exclude a queued run when the same tenant, job key and scope already has an
active non-workflow run. The queued row stays intact and becomes eligible on a
later claim after the active run turns terminal. This uses the invariant the
database already enforces and avoids another lock protocol or write delay.

## Affected areas and steps

- Operations migration replacing `jobs_claim_next_v6` and
  `jobs_claim_next_v7`, preserving source-binding resource locking and v7's
  delegation.
- Focused migration contract test for the active-scope eligibility guard.
- This plan, the registry and root blueprint.

1. Trace admission, ready promotion and claim behavior; confirm the existing
   queued and executing unique indexes preserve successor state.
2. Add the active-scope guard to both claim paths and focused contract coverage.
3. Run focused validation, prepare release 0.144.9, then commit and deploy the
   migration after user approval.

Expected migration sequence: use 0405 after the tracked 0404 migration. PLAN-049
currently also plans migration 0404 from another branch; it must rebase and
renumber to 0406 or later after this plan, before either migration branch is
merged. No production data changes are expected.

## Validation and checkpoint

Release 0.144.9 reached production, but 0405 could not apply because the
production database no longer has role `metabase_ro`; Operations is restarting
while startup retries. A correction is prepared in 0.144.10 by removing the
obsolete role from the migration's REVOKE list. The focused pytest passes after
the contract assertion correction. Next push 0.144.10, then verify migration
application, Operations health, and the claim behavior.
