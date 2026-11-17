#!/bin/sh
# Read a bounded log tail; emit only this continuation's exact markers and HTTP status.
set -eu
prefix=${1-}
case "$prefix" in *[!a-f0-9]*|'') echo invalid_prefix; exit 1;; esac
[ "${#prefix}" -eq 32 ] || { echo invalid_prefix; exit 1; }
logs=$(timeout 10 docker logs --since 12m --tail 10000 ninja-operations 2>&1) || {
    echo log_read_failed; exit 1;
}
printf '%s\n' "$logs" | awk -v prefix="$prefix" '
    index($0,"_plan056=" prefix "_") &&
    match($0,/"GET [^ ]+ HTTP\/[0-9.]+" [0-9][0-9][0-9] /) {
        row=substr($0,RSTART,RLENGTH); split(row,parts," "); status=parts[4];
        if (match(row,/_plan056=[a-f0-9]+_[0-9]+/)) {
            marker=substr(row,RSTART+9,RLENGTH-9); split(marker,m,"_");
            if (m[1]==prefix && m[2]>=1 && m[2]<=12) {
                print "completed_marker=" marker " status=" status; found=1
            }
        }
    }
    END {if (!found) print "completion_not_observed"}'
