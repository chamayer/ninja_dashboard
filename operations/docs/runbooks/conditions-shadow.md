# Conditions shadow comparison

## Purpose

Measure the proposed conditions dependency rules against current tenant data
without changing findings or their subscribers. This is an administrative CLI,
not an operator UI change. No apply mode or automatic scheduler exists.

Use the approved workspace helper for external invocation; see the operations
guide. Do not copy database credentials into commands or files. Run using the
normal Operations runtime configuration, not a migration/superuser override.

## Commands

Validate and display all 53 definitions without database access:

```sh
python manage.py compare_conditions --tenant-id 1 --catalog-only
```

Read a consistent PostgreSQL snapshot and print an aggregate JSON report:

```sh
python manage.py compare_conditions --tenant-id 1
```

The tenant ID is always explicit. Use the intended tenant, not the example ID
by habit. The command rejects SQLite, an existing transaction, an invalid
tenant, or an unknown schema. It must not be run inside an application request.

Optional bounds: `--max-rows 250000` and `--timeout-ms 30000`. Row limits apply
to each input query; exceeding a bound fails the run rather than producing a
partial comparison. The maximum per-query timeout is 60 seconds. Total run
time includes several sequential queries and in-memory participant evaluation.

An explicitly reviewed JSON profile can be supplied with `--profile PATH`.
The packaged profile uses **180 days**, not six calendar months, for extended
absence and a **48-hour** collection freshness window. Those are shadow
thresholds, not changes to existing production settings. Every report includes
the profile version and content hash.

Reports are operational output. Do not commit reports or customer data to Git.
The default output contains aggregates, not names, raw subject IDs, source URLs,
credentials, or finding evidence payloads.

## Reading the report

- `baseline_active_rows`: open, acknowledged and investigating rows, separated
  by physical table. This is not a claim about every UI's filtered count.
- `registry`: all live types compared against the 53-definition profile. New
  unknown types are reported, never silently dropped.
- `by_type`: every registered/profile type, including zero-count and historical
  definitions; category, operator type, specific label, lifecycle, disposition
  counts and reasons. Participant-scope counts can exceed condition counts.
- `comparison`: distinct candidate impacts. Identity-attributed global software
  findings and installation findings are included, with fanout counts separate.
- `consumer_state`: enabled dispatch rules, digest routes, pending source actions.
- `subscriber_coverage`: all known consumer families explicitly marked unchanged.

`eligible` means only that the evaluated shadow dependencies do not block that
scope. It is **not** permission, proof of source-action eligibility, a delivery
prediction, or a declaration that all production prerequisites were measured.

`blocked` means a measured gate failed; `unknown` means prerequisites cannot be
established; `suppressed` means attention/execution is withheld without clearing
the condition. Reasons accumulate even when another reason has higher priority.

Identity findings are never blocked by their own identity rule. Their member
snapshots are provisional input: invalid/deleted/unavailable members are counted.
An accepted distinct-identity decision requires a real readiness adapter before
enforcement; it cannot be inferred from an acknowledgment or a dismissed alert.

Missing collection scope is unknown. Even an explicitly referenced complete
snapshot cannot prove that it covers every source required by an absence rule.
A recent complete snapshot and a later incomplete attempt are not equivalent.
An old agent contact combined with an online claim is reported as contradictory
evidence, not silently classified as offline. Retired computers are excluded
from the active offline-contact adapter; retirement applicability is not inferred.

## Subscriber acceptance matrix before enforcement

| Consumer | Required additional validation |
| --- | --- |
| Issues / Admin Health | Same finding remains discoverable across storage classes; reasons and counts agree |
| Entity pages / exposure | Participant-scoped restrictions; global facts survive; no cross-client disclosure |
| Counts / client-health history | Distinct condition versus entity counts; versioned metric meaning and coverage |
| Dispatcher / digest | Shared eligibility before matching/routes/cooldowns; no stale recovery flood |
| Source actions | Permission, target, evidence and identity rechecked at execution; no duplicate action |
| Merge / mapping | Membership and readiness invalidation followed by fresh evaluation |
| Legacy / external | Preserve keys/interfaces until consumers are explicitly audited |

## Release boundary

This foundation can be deployed without migrations and without changing live
evaluators. Deployment does not itself run a comparison. Run the command after
deployment to validate the packaged code against actual data.

Before enabling policies, establish a supported identity-readiness contract,
required collection scopes, persisted/audited participant and episode state,
and consumer integration tests. Review the shadow impact and approve the
behavior-changing release. Do not interpret this command's successful exit as
approval to enable gates or rewrite historical resolved findings.
