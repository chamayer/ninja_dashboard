#!/bin/sh
# PLAN-056 task 3. Reviewed temporary diagnostics; approval required to run.
# Invoke: timeout 180 sh /tmp/<approved-dir>/plan056_host_observe.sh
# Database script must already be copied to /tmp/plan056_db_observe.py in
# ninja-operations. No settings, process arguments, raw inspect, logs or payloads.
set -eu

for tool in docker timeout awk date sha256sum df; do
    command -v "$tool" >/dev/null 2>&1 || { echo 'setup_missing_tool'; exit 1; }
done
container_ids=$(docker ps -q 2>/dev/null) || { echo 'container_list_unavailable'; exit 1; }
[ -n "$container_ids" ] || { echo 'no_running_containers'; exit 1; }

for name in ninja-postgres operations-ingest ninja-jobs-worker ninja-operations; do
    printf 'service=%s ' "$name"
    docker inspect --format '{{.Image}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no_healthcheck{{end}} {{.State.StartedAt}} {{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}' "$name" 2>/dev/null || {
        echo 'service_metadata_unavailable'; exit 1;
    }
    docker inspect --format '{{.Id}}' "$name" 2>/dev/null |
        awk -v ids="$container_ids" 'BEGIN {n=split(ids,a,"\n")} {for(i=1;i<=n;i++) if(a[i]==substr($0,1,12)) print "workload_alias=workload_" i}'
done

# Known source files only; output hashes, never contents.
docker exec ninja-operations sha256sum /app/apps/core/views.py \
    /app/apps/core/issue_selection.py /app/apps/core/software_review.py \
    /app/apps/core/patching_reads.py /app/apps/core/middleware.py \
    /app/shared/jobs_registry.py /entrypoint.sh 2>/dev/null || {
        echo 'operations_hashes_incomplete'; exit 1;
    }
docker exec operations-ingest sha256sum /app/ingest/intel/matcher.py \
    /app/shared/jobs_registry.py /app/VERSION 2>/dev/null || {
        echo 'ingest_hashes_incomplete'; exit 1;
    }
# Allowlist worker settings only; no environment dump.
docker exec ninja-operations sh -c 'for k in OPERATIONS_WORKERS OPERATIONS_THREADS OPERATIONS_TIMEOUT OPERATIONS_WORKER_CLASS; do printenv "$k" 2>/dev/null | awk -v k="$k" '\''/^[a-zA-Z0-9_-]+$/ {print k "=" $0}'\'' || true; done' 2>/dev/null
echo 'worker_values_above_are_container_environment_not_proof_of_running_master_arguments'

# Launch exactly one SQL observer. Both collectors emit UTC for correlation;
# DB metadata precedes its samples, so windows may be offset by several seconds.
timeout 120 docker exec ninja-operations python /tmp/plan056_db_observe.py &
db_observer=$!

index=0
window_started=$(date +%s)
while [ "$index" -lt 5 ]; do
    now=$(date +%s)
    delay=$((window_started + index * 15 - now))
    if [ "$delay" -gt 0 ]; then sleep "$delay"; fi
    printf 'host_sample=%s utc=%s\n' "$index" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    awk '/^cpu / || /^procs_running / || /^procs_blocked / {print}' /proc/stat
    awk '/^(MemTotal|MemAvailable|SwapTotal|SwapFree|Dirty|Writeback):/ {print}' /proc/meminfo
    awk '/^(pswpin|pswpout|pgmajfault|pgpgin|pgpgout) / {print}' /proc/vmstat
    awk '{print "load_average " $1 " " $2 " " $3 " tasks=" $4}' /proc/loadavg
    df -Pk / | awk 'NR==2 {print "root_filesystem_kb total=" $2 " used=" $3 " available=" $4}'
    # Numeric Linux disk counters, no mounted paths or volume names.
    awk '$3 ~ /^(sd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme[0-9]+n[0-9]+|dm-[0-9]+)$/ {print}' /proc/diskstats
    # Container IDs are not printed: stable aliases across the frozen window.
    # Missing statistics abort this diagnostic instead of repeating requests.
    metrics=$(timeout 8 docker stats --no-stream --format '{{.ID}} {{.CPUPerc}} {{.MemUsage}} {{.BlockIO}} {{.PIDs}}' $container_ids 2>/dev/null) || {
        echo 'container_stats_failed_stopping'; exit 1;
    }
    printf '%s\n' "$metrics" | awk -v ids="$container_ids" '
        BEGIN {n=split(ids,a,"\n"); for(i=1;i<=n;i++) alias[a[i]]=i}
        $1 in alias {$1="workload_" alias[$1]; print}'
    if ! kill -0 "$db_observer" 2>/dev/null; then
        wait "$db_observer" || { echo 'db_observer_failed_stopping'; exit 1; }
        if [ "$index" -lt 4 ]; then echo 'db_observer_ended_early'; exit 1; fi
    fi
    index=$((index + 1))
done
wait "$db_observer" || { echo 'db_observer_failed'; exit 1; }
echo 'task3_observation_complete'
