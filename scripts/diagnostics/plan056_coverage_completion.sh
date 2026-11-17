#!/bin/sh
# Explicit approval required: one historical log filter and one catalog snapshot.
set -eu
directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "$directory" in /tmp/plan056-coverage.*) ;; *) echo invalid_directory; exit 1;; esac

for service in ninja-operations ninja-postgres; do
    printf 'service=%s ' "$service"
    docker inspect --format '{{.State.Status}} {{.State.StartedAt}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no_healthcheck{{end}}' "$service" 2>/dev/null || exit 1
done

# Fixed historical interval and exact marker, no new HTTP request or raw logs.
logs=$(timeout 10 docker logs --timestamps \
    --since 2026-11-09T22:47:00Z --until 2026-11-09T23:02:00Z \
    --tail 10000 ninja-operations 2>&1) || { echo historical_log_unavailable; exit 1; }
printf '%s\n' "$logs" | awk '
    index($0,"_plan056=4d50056e260e031fdf44e47a7abfa97a_9 HTTP/") &&
    match($0,/"GET [^ ]+ HTTP\/[0-9.]+" [0-9][0-9][0-9] /) {
        request=substr($0,RSTART,RLENGTH); split(request,p," ");
        print "coverage_completed_status=" p[4];
        if ($1 ~ /^[0-9][0-9][0-9][0-9]-/) print "log_utc=" $1;
        found=1
    }
    END {if (!found) print "coverage_completion_not_observed_in_bounded_history"}'
unset logs

# Documented existing local Unix-socket inspection connection, never a grant or
# application-role replacement. No passwords/environment values are displayed.
timeout 12 docker exec -i \
    -e 'PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=3000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000' \
    ninja-postgres psql -X -q -A -t -v ON_ERROR_STOP=1 -U ninja -d ninja \
    < "$directory/plan056_coverage_completion.sql" 2>/dev/null || {
        echo catalog_snapshot_unavailable_no_retry; exit 1;
    }
echo coverage_completion_check_finished
