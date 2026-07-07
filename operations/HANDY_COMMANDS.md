# Operations — Handy Commands

Operator-facing commands for the Operations service. Run from the am-ch-01
host shell unless otherwise noted. See root `ninja-dashboard/HANDY_COMMANDS.md`
for stack-wide commands (postgres, metabase, ingest).

---

## Remote validation from workstation

The Docker host is not DNS-resolvable by name. Use the local SSH alias
`am-ch-01`, which maps to `amrose@10.61.50.28` in
`C:\Users\chamayer\.ssh\config`.

`amrose` is in the `docker` group, so use plain `docker ...` commands. Do not
prefix Docker validation commands with `sudo`; `sudo docker ...` will prompt
for a password even though plain Docker works.

```powershell
C:\Windows\System32\OpenSSH\ssh.exe am-ch-01 "hostname && id"
C:\Windows\System32\OpenSSH\ssh.exe am-ch-01 "docker ps"
C:\Windows\System32\OpenSSH\ssh.exe am-ch-01 "docker logs --tail=120 ninja-operations"
C:\Windows\System32\OpenSSH\ssh.exe am-ch-01 "curl -fsS http://127.0.0.1:8091/healthz"
```

Expected basics:

- `id` includes `docker`.
- `ninja-operations` is `healthy`.
- `/healthz` returns `{"status": "ok"}` from the host loopback binding.
- Startup logs show migrations, initial admin password sync, client bootstrap,
  device bootstrap, static collection, then Gunicorn startup.

Data validation:

```powershell
C:\Windows\System32\OpenSSH\ssh.exe am-ch-01 "docker exec ninja-operations python manage.py showmigrations"
C:\Windows\System32\OpenSSH\ssh.exe am-ch-01 "docker logs ninja-operations 2>&1 | head -40"
```

The Operations runtime role is RLS-protected. A plain Django shell count without
tenant context can return zero rows even when bootstrap succeeded. Either wrap
ORM checks in `tenant_context(1)` or query counts through Postgres:

```powershell
C:\Windows\System32\OpenSSH\ssh.exe am-ch-01 'docker exec ninja-postgres psql -U ninja -d ninja -c "SELECT ''clients'' AS table_name, COUNT(*) FROM operations.clients UNION ALL SELECT ''client_links'', COUNT(*) FROM operations.client_links UNION ALL SELECT ''devices'', COUNT(*) FROM operations.devices UNION ALL SELECT ''device_links'', COUNT(*) FROM operations.device_links ORDER BY table_name;"'
```

If SSH prints a `known_hosts` update warning but the remote command succeeds,
record the warning separately. It is a local SSH-client issue, not an
Operations deployment failure.

## One-time Postgres role bootstrap

Only needed on a fresh Postgres (or after DR). Creates the `operations_migrate`
role so migration `0006_rls_roles_policies_grants` can execute. Migration then
creates the other five roles idempotently.

```bash
# Read both passwords out of the bind-mounted .env, feed to psql.
MIG_PW=$(grep '^OPERATIONS_MIGRATE_DB_PASSWORD=' /amr-ch-01_data/ninja-dashboard/.env | cut -d= -f2-)
APP_PW=$(grep '^OPERATIONS_DB_PASSWORD='         /amr-ch-01_data/ninja-dashboard/.env | cut -d= -f2-)

docker exec -i ninja-postgres psql -U ninja -d ninja \
    -v migrate_pw="${MIG_PW}" \
    -v app_pw="${APP_PW}" \
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
