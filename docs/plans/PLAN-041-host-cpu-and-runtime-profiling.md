# PLAN-041 — Host CPU and runtime profiling

## Status and goal

Active. Attribute live resource use and identify the measured dominant Ninja
phase before changing its queries or scheduling. Commit and push approved
2026-11-02; prepare release 0.142.1. No new ingest or Django migrations.

## Scope and affected files

- `ingest/evaluator.py`, `ingest/identity/matching.py`: private-data-free timings.
- `ingest/tests/test_cpu_diagnostics.py`: behavior and diagnostic privacy checks.
- `VERSION`, `CHANGELOG.md`: paired release metadata.
- Root routing, registry, backlog pointer, and the
  [measurement record](../records/HOST-CPU-2026-11-02.md).
- Sibling DMARC repository owns the lightweight health probe, monitoring
  retirement, and independent parser HTTP checker.

## Steps and decisions

1. Attribute container/process CPU and pressure; follow a full processing cycle.
2. Add elapsed phase/cache-miss diagnostics without matching or data changes.
3. Review migration parity, commit and push origin then the required mirror.
4. Verify the automatic deployment and collect phase timings in a subsequent
   cycle; use that evidence to select a bounded optimization.

No new dependencies, schema changes, data rebuilds, or host tuning. Do not use
Zabbix to monitor the parser. The excluded-record cache hypothesis was ruled
out; matching rules and cache behavior remain intact.

## Validation and checkpoint

24 focused tests passed; compilation, scoped Ruff, and whitespace checks passed.
The ingest image includes both changed modules. Live comparison found no
pending SQL or Operations Django migrations before this release. Full-cycle
timings and competing host workloads are in the measurement record; elapsed
time includes API and lock waits and is not CPU time.

## Next action

Commit the reviewed scope, push origin then the mirror without an intervening
deployment check, and verify the automatic Portainer rollout. Do not request a
separate Ninja redeploy. Preserve unrelated workspace files. Record deployed
hashes in the existing evidence record without a hash-only follow-up commit.
