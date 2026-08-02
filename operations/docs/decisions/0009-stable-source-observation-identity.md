# 0009 — Stable source observation identity

Status: Accepted (not implemented)
Date: 2026-07-31

## Context

ADR-0007 is accepted and deployed through v5. Its current observation key is:

```text
(tenant_id, source_binding_id, entity_type, parent_source_key, entity_key)
```

That key mixes external identity with two mutable implementation details.

- A source binding is a source instance paired with a collector instance.
  Replacing the collector creates a new binding even though the external
  account and every record in it are unchanged.
- `entity_type` is Operations' mutable classification. Retyping a source
  record, including moving a Hudu asset between layouts, does not create a new
  external record.

The deployed reconciliation path is also binding-scoped. After a collector
replacement, the old binding's current rows can remain active while the new
binding writes another set. This creates duplicate live evidence rather than
a safe handoff.

Source namespaces and source classifications are distinct concepts. Ninja
device `192` and Ninja location `192` are different because their namespaces
differ. Hudu asset `123` remains the same record when its layout changes.

## Options considered

- **Keep the deployed key.** Rejected because collector replacement and
  reclassification change identity.
- **Key on `native_record_type`.** Rejected because native type/layout is
  mutable source classification.
- **Key on source instance and stable external namespace.** Selected because
  it follows the external system's durable identifier domain.
- **Prevent concurrent or replacement bindings.** Rejected because transport
  topology must not define business identity and safe handoff is required.

## Decision

### Stable identity tuple

Observation current and history use:

```text
(tenant_id, source_instance_id, external_namespace,
 parent_external_namespace, parent_external_id, external_id)
```

The governing rule is: **nothing an operator can change in the source may be
part of source-record identity.**

- `source_instance_id` identifies the external account or connection.
- `external_namespace` identifies the vendor's stable ID domain, such as
  `device`, `location`, or `asset`.
- Parent namespace and ID are included because some child IDs are unique only
  inside a parent.
- `external_id` is the record ID within that namespace and parent scope.

The four string identity components are non-null and non-empty except for
top-level parent components, which are both normalized to the empty string.
A check constraint requires parent namespace and parent ID to be either both
empty or both populated. This avoids PostgreSQL NULL uniqueness semantics
creating duplicate top-level identities.

### Current-source namespace and backfill rules

The initial migration uses these connector-owned external ID domains. These
names describe vendor record namespaces, not Operations classifications.

| Source record family | External namespace | External ID rule |
| --- | --- | --- |
| Ninja `/devices-detailed`, including every node classification | `device` | Ninja device ID |
| Ninja organization | `organization` | Ninja organization ID |
| SentinelOne agent | `agent` | SentinelOne agent ID |
| SentinelOne site | `site` | SentinelOne site ID |
| ScreenConnect access record | `access-session` | ScreenConnect `SessionID` |
| ScreenConnect synthetic per-instance container | `source-instance` | Constant `self` |
| LogMeIn host | `host` | LogMeIn host ID |
| LogMeIn group | `group` | LogMeIn group ID |
| Hudu asset | `asset` | Hudu asset ID |
| Hudu company | `company` | Hudu company ID |

All currently deployed records are top-level; both parent components backfill
to the empty string. A future child record must supply both its parent
namespace and parent ID explicitly. The ScreenConnect container is synthetic,
so its stable identity is the source instance itself plus constant `self`;
the editable legacy source key/name is retained only as compatibility data.

Ninja node classification remains mutable metadata: `agent.rmm`, `vm.guest`,
`vm.host`, `network.device`, `monitor.target`, and `unknown` all share the
Ninja `device` namespace. Ninja `/device-health` is not currently an Operations
observation row; its later generic-ingest migration uses the distinct
`device-health` namespace required by ADR-0010. Software installations remain
in their dedicated device-scoped current/history tables and are outside this
observation-identity backfill.

### Mutable observation metadata

The following are not identity:

- `native_record_type`: the source's mutable discriminator or layout.
- `entity_type` and canonical class: Operations classification.
- `last_seen_binding_id`: nullable collection provenance, updated when a new
  binding transports the record and `ON DELETE SET NULL`.

Classification changes are material history transitions under the same
identity: close the prior SCD-2 interval and open a new interval. They do not
withdraw and recreate the source record.

### Snapshot runs and membership

`observation_snapshot_runs` is scoped by tenant, source instance, and snapshot
scope. It records the transporting binding, `run_started_at`, completion
status, and completion time.

Every run records explicit membership using the full source identity rather
than a mutable `last_snapshot_run_id` pointer or a hash as the authority:

```text
observation_snapshot_membership(
    tenant_id, run_id,
    external_namespace,
    parent_external_namespace, parent_external_id,
    external_id
)
```

The primary key contains all listed columns. A digest may be added as a lookup
optimization, but never replaces the collision-free key.

### Reconciliation rules

1. Collection may overlap, but reconciliation serializes with a transaction
   advisory lock on `(tenant_id, source_instance_id, snapshot_scope)`.
2. Only a completed, explicitly complete snapshot may withdraw evidence.
   Partial, failed, or abandoned runs withdraw nothing.
3. Run `R` may withdraw a current row only when the identity is absent from
   `R` and the row's `last_received_at` is earlier than `R.run_started_at`.
   Evidence received after the run began outranks that run's absence claim.
4. If overlapping complete runs disagree about membership, disputed rows are
   preserved and a finding records both runs. The system does not guess.
5. The next non-overlapping complete run may confirm or withdraw disputed rows
   normally and automatically resolve the finding.
6. Withdrawal records both the deciding run and the transporting binding.
7. The existing per-identity advisory lock and out-of-order `observed_at`
   guard remain, re-keyed to the stable tuple.

### Migration

Migration is expand, backfill, shadow/dual operation, comparison, read/write
cutover, then contract.

- Derive source instance from the existing binding.
- Derive namespaces by a written, reviewed rule for each current source.
- Do not guess unresolved namespaces or parent scope; retain the legacy row and
  raise a finding.
- Rebuild unique constraints, lock keys, upserts, history close/open,
  reconciliation, snapshot runs, retention, RLS, seeds, and dependent views.
- Retain legacy identity columns until every row is accounted for and rollback
  has been rehearsed. Contract work requires separate approval.

## Rationale

- Collector replacement becomes a transport change rather than fleet-wide
  identity churn.
- Source-side reclassification preserves history continuity.
- Observation identity and generic source-link identity share one definition.
- Explicit run membership makes absence decisions auditable and concurrency
  safe.
- Full identity columns avoid relying on probabilistic hash uniqueness.

## Consequences

**Required**

- Connectors must emit stable namespace separately from native record type.
- Every current source needs an approved namespace/backfill rule.
- Material hashes include classification, normalized claims, relays, and
  observed relationships when changes to them must open history.
- Tests cover collector replacement, concurrent bindings, reclassification,
  parent-scoped IDs, partial/failed snapshots, out-of-order writes, overlapping
  disagreement, and later self-healing.

**Prohibited**

- Using binding, native type, Operations type, display name, or another mutable
  field in source identity.
- Reconciling absence across an entire vendor catalog rather than the exact
  source-instance snapshot scope.
- Dropping legacy identity columns before cutover accounting and separately
  approved contract work.

## Supersedes or superseded by

When implemented and deployed, this record supersedes only ADR-0007's observation
identity and reconciliation-scope rules. ADR-0007's current/history split,
SCD-2 semantics, material hashing, out-of-order protection, raw-data policy,
and retention rules remain in force.

ADR-0010 depends on this record; this record does not depend on ADR-0010 and
may be implemented as an independent corrective track. Until implementation
and deployment, ADR-0007 v5 remains the authority for implemented behavior.
