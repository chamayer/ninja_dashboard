#!/bin/sh
# Approved task 4 only: invoke by path from a fresh verified temporary directory.
# Contains no profile values, secret access, deployments or broad process control.
set -eu
directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "$directory" in /tmp/plan056-task4matrix.*) ;; *) echo invalid_directory; exit 1;; esac
done_file="$directory/observer.done"
test ! -e "$done_file"
docker exec ninja-operations test ! -e /tmp/plan056-task4-stop

observe() {
    index=0
    started=$(date +%s)
    while [ "$index" -lt 49 ] && [ ! -e "$done_file" ]; do
        delay=$((started + index * 15 - $(date +%s)))
        if [ "$delay" -gt 0 ]; then sleep "$delay"; fi
        [ ! -e "$done_file" ] || break
        printf 'host_sample=%s utc=%s\n' "$index" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        awk '/^cpu / || /^procs_running / || /^procs_blocked / {print}' /proc/stat || return 1
        awk '/^(MemTotal|MemAvailable|SwapTotal|SwapFree|Dirty|Writeback):/ {print}' /proc/meminfo || return 1
        awk '/^(pswpin|pswpout|pgmajfault) / {print}' /proc/vmstat || return 1
        awk '$3 ~ /^(sd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme[0-9]+n[0-9]+)$/ {print}' /proc/diskstats || return 1
        timeout 8 docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}} {{.BlockIO}}' \
            ninja-postgres ninja-jobs-worker operations-ingest ninja-operations 2>/dev/null || return 1
        index=$((index + 1))
    done
}

(
    observe || {
        echo host_observer_failed
        docker exec ninja-operations touch /tmp/plan056-task4-stop
        exit 1
    }
) &
observer=$!
status=0
timeout 720 docker exec ninja-operations python /tmp/plan056_http_matrix.py || status=$?
touch "$done_file"
wait "$observer" || status=1
printf 'matrix_wrapper_exit=%s\n' "$status"
exit "$status"
