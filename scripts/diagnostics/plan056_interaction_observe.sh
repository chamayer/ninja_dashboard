#!/bin/sh
# Approval required. Metadata only; no raw SQL, command lines or volume paths.
# Invoke through the shared helper: timeout 105 sh /tmp/plan056-interaction.XXXXXX/...
set -eu
directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
case "$directory" in /tmp/plan056-interaction.*) ;; *) echo invalid_directory; exit 1;; esac
for tool in docker timeout awk date findmnt getconf; do
    command -v "$tool" >/dev/null 2>&1 || { echo missing_tool; exit 1; }
done
for file in plan056_interaction_gate.sql plan056_interaction_sample.sql; do
    [ -f "$directory/$file" ] || { echo missing_sql; exit 1; }
done
# One short preflight connection; no sampler or host capture on gate failure.
timeout 10 docker exec -i \
    -e 'PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=3000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000 -c application_name=plan056_interaction_gate' \
    ninja-postgres psql -X -q -A -t -v ON_ERROR_STOP=1 -U ninja -d ninja \
    < "$directory/plan056_interaction_gate.sql"
# Map only the documented data-volume destination; keep the source path private.
volume_path=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{println .Source}}{{end}}{{end}}' ninja-postgres 2>/dev/null) || { echo data_mount_inspection_failed; exit 1; }
[ -n "$volume_path" ] || { echo data_mount_unknown; exit 1; }
device=$(findmnt -n -o MAJ:MIN -T "$volume_path" 2>/dev/null) || { echo device_mapping_failed; exit 1; }
case "$device" in *[!0-9:]*|'') echo device_mapping_unknown; exit 1;; esac
unset volume_path
printf 'database_device=%s clock_ticks=%s page_bytes=%s\n' "$device" "$(getconf CLK_TCK)" "$(getconf PAGESIZE)"

host_snapshot() {
    printf 'host_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    awk '/^cpu / || /^procs_running / || /^procs_blocked / {print}' /proc/stat
    awk '/^(MemTotal|MemAvailable|SwapTotal|SwapFree|Dirty|Writeback):/ {print}' /proc/meminfo
    awk '/^(pswpin|pswpout|pgmajfault|pgpgin|pgpgout) / {print}' /proc/vmstat
    for pressure in cpu memory io; do
        [ -r "/proc/pressure/$pressure" ] || { echo pressure_unavailable; continue; }
        awk -v resource="$pressure" '{print "pressure",resource,$0}' "/proc/pressure/$pressure"
    done
    awk -v device="$device" '$1 ":" $2 == device {print "database_disk",$0; found=1} END {if(!found) print "database_disk_counter_unavailable"}' /proc/diskstats
    # docker top receives no command/args columns. Cap and flag the process list.
    process_ids=$(timeout 3 docker top ninja-postgres -eo pid) || return 1
    printf '%s\n' "$process_ids" | awk 'NR>1 && $1~/^[0-9]+$/ {n++} END {print "postgres_process_count=" n; if(n>50) print "postgres_processes_truncated"}'
    for host_pid in $(printf '%s\n' "$process_ids" | awk 'NR>1 && NR<=51 && $1~/^[0-9]+$/ {print $1}'); do
        if [ ! -r "/proc/$host_pid/stat" ] || [ ! -r "/proc/$host_pid/status" ]; then
            echo backend_process_disappeared; continue
        fi
        namespace_pid=$(awk '/^NSpid:/ {print $NF}' "/proc/$host_pid/status")
        [ -n "$namespace_pid" ] || { echo namespace_pid_unavailable; continue; }
        # Strip parenthesized comm, which can contain whitespace; never output it.
        awk -v pid="$namespace_pid" '{sub(/^.*\) /, ""); print "backend_process",pid,"utime=" $12,"stime=" $13,"start_ticks=" $20,"rss_pages=" $22}' "/proc/$host_pid/stat" 2>/dev/null || echo backend_stat_unavailable
        if [ -r "/proc/$host_pid/io" ]; then
            awk -v pid="$namespace_pid" '/^(read_bytes|write_bytes|cancelled_write_bytes):/ {print "backend_io",pid,$0}' "/proc/$host_pid/io" 2>/dev/null || echo backend_io_unavailable
        else
            echo backend_io_unavailable
        fi
    done
}

# One subsequent sampling connection; there is at most one observer at a time.
# Buffer host-only metadata to avoid interleaved SQL/host result lines.
host_capture="$directory/host.capture"
producer_failure="$directory/producer.failed"
[ ! -e "$host_capture" ] && [ ! -e "$producer_failure" ] || { echo output_exists; exit 1; }
umask 077
set -C
: > "$host_capture"
set +C
(
    window_started=$(date +%s)
    index=0
    while [ "$index" -lt 13 ]; do
        now=$(date +%s)
        delay=$((window_started + index * 5 - now))
        if [ "$delay" -gt 0 ]; then sleep "$delay"; fi
        if [ "$delay" -lt -4 ]; then
            echo host_sampling_overrun >> "$host_capture"
            : > "$producer_failure"
            printf 'SELECT 1/0;\n'
            exit 1
        fi
        if ! host_snapshot >> "$host_capture"; then
            : > "$producer_failure"
            printf 'SELECT 1/0;\n'
            exit 1
        fi
        printf "SELECT jsonb_build_object('section','sample','index',%s,'utc',clock_timestamp());\n" "$index"
        cat "$directory/plan056_interaction_sample.sql"
        index=$((index + 1))
    done
) | timeout 80 docker exec -i \
    -e 'PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=3000 -c lock_timeout=1000 -c idle_in_transaction_session_timeout=5000 -c application_name=plan056_interaction' \
    ninja-postgres psql -X -q -A -t -v ON_ERROR_STOP=1 -U ninja -d ninja || {
    cat "$host_capture"
    echo interaction_observer_failed
    exit 1
}
cat "$host_capture"
[ ! -e "$producer_failure" ] || { echo host_observer_failed; exit 1; }
echo interaction_observation_complete
