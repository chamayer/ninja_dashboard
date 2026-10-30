# PLAN-004 — Aggregate source-record review, 2026-10-28

Authorized aggregate-only production review; no production mutation, refresh,
evaluation, collection or repair. Queries used separate bounded repeatable-read,
read-only transactions with tenant 1 context. Counts across transactions are not
one simultaneous snapshot. The inspected six ingest files and Operations reader
and merge template matched committed `b393c57` by SHA-256; unrelated local edits
were not treated as deployment authority. The [handoff](../plans/PLAN-004-source-record-review.md)
owns the pending design work.

## Confirmed measurements

- Present identity records without a Computer: ScreenConnect 297, LogMeIn 22,
  R-U-ON 5. ScreenConnect includes 83 without a source group. Hudu's 5,196
  unlinked asset records include other asset classes and are not an identity
  defect count.
- After serial rejection and roaming guards, 162 unlinked ScreenConnect records
  share a usable serial with evidence on exactly one attached Computer; each
  also has a MAC shared with peer evidence. Twenty-six have same-instance,
  namespace and record-type peers. Three have a peer Computer with an active
  duplicate issue, but none appears in that issue's record list. This is not
  attachment eligibility: ownership, exclusions, virtual/shared identifiers,
  historical identity and simultaneous/sequential activity remain to review.
- Source-duplicate reconciliation: 252 stored active rows, 230 current detector
  groups, all 230 represented; 22 stored rows lack a current predicate. Nine
  current groups span source instances. This does not authorize closure or
  establish those nine groups as false positives.
- Client-group reconciliation: 34 active admin unattached-group findings; 31
  refer to present unassigned groups, two to withdrawn groups, one to an assigned
  group. Thirty-one source/group keys overlap the 36 entity unmatched-group
  findings. Instance/namespace and corrective-action scope must precede merging.
- All 36 unmatched-group entity rows, the one unnamed-group entity row and the
  one shared-serial row lack assessments. Of 252 source-duplicate rows, 231 have
  a fresh current-policy assessment. Assessment presence alone does not establish
  participant eligibility or permit closure.
- ScreenConnect: 1,674 present sessions have no canonical contact timestamp;
  776 report Offline and a contact older than 90 days. Ninety days is a
  diagnostic bucket, not an approved cleanup threshold. All 659 R-U-ON agent
  records lack canonical contact timestamps by the connector's timezone policy.
- The Computer reader's platform-level status differs from individual record
  status for 132 attached ScreenConnect records (LogMeIn 3, Ninja 5, R-U-ON 1,
  SentinelOne 15). This motivated the separately approved status/contact repair.
- Under `operations_app`, the safe metadata view exposes unassigned evidence;
  switching to an unrelated tenant context returns zero records.

The registered `unlinked_external_identity` type has zero active findings and no
current emitting producer was found. Assess reuse before proposing a new type.
Per-session stale cleanup remains distinct from Computer offline/stale-data and
the retired source-withdrawal rule. These measurements do not complete the
all-source lifecycle/action design or determine automatic attachment policy.
