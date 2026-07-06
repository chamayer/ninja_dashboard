# Operations — Handy Commands

Operator-facing commands for the Operations service. Run from the am-ch-01
host shell unless otherwise noted. See root `ninja-dashboard/HANDY_COMMANDS.md`
for stack-wide commands (postgres, metabase, ingest).

---

## One-time Postgres role bootstrap

Only needed on a fresh Postgres (or after DR). Creates the `operations_migrate`
role so migration `0006_rls_roles_policies_grants` can execute. Migration then
creates the other five roles idempotently.

```bash
# Read the migrate password out of the bind-mounted .env, feed to psql.
MIG_PW=$(grep '^OPERATIONS_MIGRATE_DB_PASSWORD=' /amr-ch-01_data/ninja-dashboard/.env | cut -d= -f2-)

docker exec -i ninja-postgres psql -U ninja -d ninja \
    -v migrate_pw="'${MIG_PW}'" \
    < /path/to/repo/operations/sql/bootstrap-roles.sql
```

Safe to re-run — refreshes the password if the role already exists. Re-invoke
whenever `OPERATIONS_MIGRATE_DB_PASSWORD` in `.env` is rotated.

---

## Health

```bash
# Loopback health endpoint (port 8091 is bound to 127.0.0.1 only).
curl -fsS http://127.0.0.1:8091/healthz
```

Expect `200 OK` with a small JSON body. Reachable from am-ch-01 host and
from other containers on the docker network at `http://operations:8091`.

---

## Verify Postgres roles + RLS

```bash
# All six roles should exist after first successful migrate.
docker exec -it ninja-postgres psql -U ninja -d ninja -c "\du"

# All operations tables should have rowsecurity=t and forcerowsecurity=t.
docker exec -it ninja-postgres psql -U ninja -d ninja -c \
    "SELECT schemaname, tablename, rowsecurity, forcerowsecurity
       FROM pg_tables
      WHERE schemaname='operations'
      ORDER BY tablename;"
```

---

## Migration status

```bash
# Django's view of what's applied.
docker exec -it ninja-operations python manage.py showmigrations
```

If nothing is applied, the entrypoint's migrate step failed silently. Check
container logs:

```bash
docker logs --tail=200 ninja-operations
```

---

## Set / reset admin password

The seed migration creates an `admin` superuser with an unusable password
(break-glass only). Set a real password before use:

```bash
docker exec -it ninja-operations python manage.py changepassword admin
```

Then log in at `http://am-ch-01:3002/admin/`.

---

## Django shell inside the container

```bash
docker exec -it ninja-operations python manage.py shell
```

Runs under the `operations_app` runtime role — subject to RLS. Use
`from apps.core.db.tenant import tenant_context` and wrap queries in
`with tenant_context(1): ...` to satisfy the tenant GUC assertion.
