# PLAN-012 — Computer reads and inventory checkpoint

This record is a partial reconstruction of the PLAN-012 handoff moved out of
the root blueprint on 2026-10-26. It preserves summarized scope, decisions,
validation limits, and the completion gate; it does not preserve the former
consumer ledger, proposed read design, affected-file inventory, or detailed
resumable implementation slices. The current checkpoint is in
[`BLUEPRINT.md`](../../BLUEPRINT.md). **Do not resume PLAN-012 until its owner
has restored or reconstructed those details and confirmed the handoff against
current source.** This record is not evidence that nothing needed was lost.

## Goal and boundaries

Reconcile every platform inventory consumer's Computer, Device, Entity, and
source-record counts and destinations. Reuse `operations.v_device` for current
Computer membership. Keep Computer, source-record, and display-row units
distinct; the count, filtered destination, and CSV must agree. Keep search and
history exceptions explicit. Do not add a projection or migration without
measurements that justify it. PLAN-014 owns requirement applicability, finding
cover, and stored verdict writing; preserve PLAN-013 authentication behavior.

## Confirmed decisions and evidence

- The shared current-Computer selector is the membership boundary. Domain
  readers may apply narrower eligibility filters, but unlinked source evidence
  and presentation rows do not become Computers.
- Source Records use observation/record grain, including unlinked records.
  Computer attachment, client attribution, and parent association remain
  separate facts.
- Inventory evidence should be bounded by the Computer population that can
  render. Keep source and Hudu evidence separate from canonical Computer
  totals.
- Consumer coverage spans Dashboard, Clients, Computer overview, inventory,
  Patching, software readers and drill-throughs, Sources, Source Records,
  entity/admin counts, and search/history exceptions. Patching and software
  remain domain-specific subsets. Counts and destinations retain their stated
  grain rather than being forced to match across unlike populations.
- The 2026-10-23 read-only measurement found 5,506 current Computers and
  37,094 current observations. The Source Records count took about 959 ms; its
  unfiltered first page took about 4.9 s because tenant/last-seen ordering was
  unsupported by an index. The Computer count took about 67 ms. This supports
  investigating the ordered read path, not adding a projection. These are
  dated measurements, not current production state.
- The 2026-10-21 baseline (from the earlier compact checkpoint, commit
  `b636df92`): deployed 0.128.15 measured a 4.740-second Computers browser
  first response, of which 3.154 seconds was database wait across 15 fleet
  reads and 1.209 seconds template rendering, before `cc5d936` stored
  evaluator requirement verdicts (ADR-0035, migration 0332). After the first
  verdict pass (2026-10-21 17:48 UTC), 19,012 verdicts were present and Hudu
  Missing on the page fell from 4,208 to 260. A drift check found 582 open
  findings with no matching verdict, explained by PLAN-014's separate resolver
  rule copy. `453c41c` and `ccae6da` were requested page fixes, not
  read-model progress. Each prerequisite run had only the eight failures also
  present on `3091a47`. These are dated measurements, not current state.
- An index draft was withdrawn; migration number 0343 is occupied. Any index
  requires a newly reviewed migration and separate approval.

## Recorded implementation checkpoint

The 2026-10-23 root checkpoint recorded Slices 0–5 as implemented locally:
Slice 0 established a consumer ledger; Slice 1 migrated Dashboard, Computer
overview, and Admin Data; Slice 2 covered Clients; Slice 3 covered Computers
inventory and Source Records; Slice 4 covered Patching/software populations
and destinations; Slice 5 covered source/entity/search surfaces. The
checkpoint also recorded current-Computer scoping for software summaries,
complete pagination, distinct source/entity grains, and card semantics. Slice 6
measured full-fleet serving cost and left optimization conditional on evidence.
Some work was committed locally and some remained uncommitted at that
checkpoint. Reconcile current files and Git before treating any slice as
complete now.

Acceptance requires one canonical Computer counted once; unlinked evidence
never presented as a Computer; count, filter, destination, and complete CSV
membership agreement before pagination; and explicit exceptions for historical
search. Preserve stored-verdict authority, Hudu/current/withdrawn distinctions,
tenant access boundaries, and rebuildability/freshness reporting for any future
projection. The old 500-row destination caps were specifically in scope.

Validation recorded at that time included focused reader/coverage checks,
`manage.py check`, Python compilation, registry validation, Ruff checks, and
scoped whitespace checks. Data-backed membership comparisons were not locally
available; Django/pytest and database configuration limitations were recorded
for the relevant workstation environment. Production read results above were
aggregate-only and made no data changes.

## Completion gate

PLAN-012 remains incomplete until each item is fixed or closed with evidence:

1. Define one effective operational-status reader for online state, contact,
   lifecycle, and client `offline_after_days`; reconcile the 30-day
   `computer_listing` window.
2. Migrate requirement readers to `device_requirement_state`; PLAN-014 owns
   applicability and verdict policy.
3. Record per-source contact semantics and label presence versus lifecycle
   evidence.
4. Reconcile effective-attribute promotion, failure/retry behavior, and the
   unverified one-cycle lag.
5. Audit SQL-view and Metabase readers of `assets`, `agent_instances`, and
   `os_installations`; retain with named readers or propose approved retirement.
6. Re-measure Source Records and relevant Computer/inventory paths; decide on
   ordering index, bloat, and heartbeat-writer work from evidence.
7. Verify whether multi-card Hudu evidence duplicates Computer-page source
   rows; correct only if demonstrated.

Production reads, schema changes, migrations, writes, deployments, commits,
and pushes retain their separate authorization gates. See the PLAN-012 section
in the root blueprint and `docs/records/PLAN_REGISTRY.md` for the current
resume gate and owner routing.
