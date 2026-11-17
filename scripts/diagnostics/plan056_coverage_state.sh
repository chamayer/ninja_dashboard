#!/bin/sh
# User-requested item 1; exact log marker and read-only catalog inspection only.
set -eu
directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "$directory" in /tmp/plan056-coverage-state.*) ;; *) echo invalid_directory; exit 1;; esac

for service in ninja-operations ninja-postgres; do
    printf 'service=%s ' "$service"
    docker inspect --format '{{.State.Status}} {{.State.StartedAt}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no_healthcheck{{end}}' "$service"
done

logs=$(timeout 10 docker logs --timestamps --since 2026-11-10T19:40:00Z \
    --tail 10000 ninja-operations 2>&1) || { echo log_read_failed; exit 1; }
printf '%s\n' "$logs" | awk '
    {lines++}
    index($0,"_plan056=62ad7d19b5852731439864bb631ca2bf_25 HTTP/") &&
    match($0,/"GET [^ ]+ HTTP\/[0-9.]+" [0-9][0-9][0-9] /) {
        request=substr($0,RSTART,RLENGTH); split(request,p," ");
        print "coverage_completed_status=" p[4];
        if ($1 ~ /^[0-9][0-9][0-9][0-9]-/) print "log_utc=" $1;
        found=1
    }
    END {
        print "bounded_log_lines=" lines;
        if (lines>=10000) print "log_tail_may_be_truncated";
        if (!found) print "coverage_completion_not_observed_in_bounded_history"
    }'
unset logs

timeout 12 docker exec -i \
    -e 'PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=3000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000' \
    ninja-postgres psql -X -q -A -t -v ON_ERROR_STOP=1 -U ninja -d ninja \
    < "$directory/plan056_coverage_state.sql"
echo coverage_state_check_finished
