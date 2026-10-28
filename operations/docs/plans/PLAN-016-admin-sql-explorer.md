# PLAN-016 — Admin read-only SQL explorer

## Goal

Provide an Operations Admin page for bounded read-only production-data
inspection, including the guard-aware identity reattachment-candidate query.

## Scope

- Admin-only GET/POST page under Admin Data.
- Single SQL statement executed in a `READ ONLY` transaction with tenant 1
  forced server-side, a short statement timeout, and a fixed result limit.
- Reject multi-statement input and non-query statements before execution.
- Render bounded tabular results; do not add exports, saved user queries,
  mutation capability, schema changes, or deployment.
- Ship the 110-candidate query as a selectable saved query.

## Security decision

The database transaction is the enforcement boundary: `READ ONLY` blocks
database writes even if lexical validation is bypassed. The application uses
its existing runtime role and tenant context. Lexical validation is a usability
and defense-in-depth guard, not the authority. Results stay in the authenticated
admin UI and are capped.

## Validation

- Non-admin access is denied.
- A query executes with tenant context and bounded results.
- DML, multi-statement, and timeout-prone queries are rejected or fail closed.
- The saved identity query renders.

## Checkpoint

Defined and active on 2026-10-21. No production behavior has changed.
