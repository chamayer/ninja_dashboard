# Operations run and maintenance guide

This document contains safe operational guidance without private host values or
credentials.

## Runtime

Operations runs as a Django/gunicorn service in the root Compose stack. It uses
Postgres and shares source/derived data with the ingest engine.

Settings:

- Development settings for controlled local checks
- Production settings that require explicit secret and allowed-host
  configuration

## Startup sequence

The production entrypoint is responsible for the approved subset of:

1. Loading external environment configuration
2. Applying Django migrations with the migration role
3. Collecting static files
4. Synchronizing initial administrative access without invalidating sessions
   unnecessarily
5. Starting gunicorn with the restricted runtime role

Bootstrap commands must not become privileged alternate ingest paths.

## Health and validation

After deployment:

- Confirm the Operations container is healthy.
- Confirm the health endpoint returns success.
- Confirm Django migration status.
- Inspect startup logs for migration, bootstrap, static-file, and gunicorn
  failures.
- Exercise the changed page or endpoint.
- Confirm RLS-aware database results.

## Tenant-aware validation

The runtime role is protected by RLS. An ORM query without tenant context may
return zero rows even when data exists.

Use one of:

- The application tenant-context helper
- A request path that establishes tenant context
- An approved database-side count/query with the appropriate validation role

Do not disable RLS merely to simplify a diagnostic.

## Standard checks

Use the relevant subset in the documented environment:

```text
python manage.py check
ruff check .
ruff format --check .
pytest <target>
```

For migration changes, also review the migration plan and perform focused
schema/permission checks.

## Database roles and migrations

- Migration and runtime roles are separate.
- New tables and views require appropriate grants and tenant policies.
- Raw SQL migrations and Django state must agree.
- `SeparateDatabaseAndState` or unmanaged models require explicit explanation.
- PostgreSQL procedural blocks must not assume ordinary `psql -v`
  interpolation.

## Derived-state rebuilds

Before a rebuild:

- Identify canonical and operator-authored tables that must be preserved.
- Identify derived tables/views safe to truncate or refresh.
- Record the accepted history loss, if any.
- Back up affected state.
- Deploy corrected writers before clearing derived data.

After a rebuild:

- Verify source counts, canonical counts, links, candidates, and findings.
- Check known high-risk identity cases.
- Confirm refresh functions and queues return to healthy state.

## Recovery

- Preserve evidence and logs before retrying a failed migration or refresh.
- Cancel a blocked database operation only with explicit approval and a clear
  rollback plan.
- Do not apply destructive legacy cutover steps until consumer audits and
  backups are complete.
