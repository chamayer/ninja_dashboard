#!/bin/sh
# Read one bounded access-log tail and emit only the exact pilot marker/status.
# Approval required; no raw log output. Usage: sh <this-file> <32hex>_1
set -eu
marker=${1-}
prefix=${marker%_1}
case "$prefix" in *[!a-f0-9]*|'') echo invalid_marker; exit 1;; esac
[ "${#prefix}" -eq 32 ] && [ "$marker" = "${prefix}_1" ] || { echo invalid_marker; exit 1; }
logs=$(timeout 8 docker logs --since 120s --tail 5000 ninja-operations 2>&1) || {
    echo log_read_failed; exit 1;
}
printf '%s\n' "$logs" | awk -v marker="$marker" '
    index($0,"_plan056=" marker " HTTP/") &&
    match($0,/"GET [^ ]+ HTTP\/[0-9.]+" [0-9][0-9][0-9] /) {
        row=substr($0,RSTART,RLENGTH); n=split(row,parts," ");
        print "completed_marker=" marker " status=" parts[4]; found=1
    }
    END {if (!found) print "completion_not_observed"}'
