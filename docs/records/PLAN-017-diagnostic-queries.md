# PLAN-017 — Exact diagnostic drafts for Phase 1 gate review

2026-10-25. Status: **unexecuted review draft**. This is neither production
authorization nor a runtime script. Claude must review these exact statements,
roles, request shapes, limits and gaps before any user approval request.
The [gate ledger](PLAN-017-phase-1-gate.md) records coverage and remaining work.
No SQL below has been sent to a database, including a local database.

Reader-baseline update: concurrent work added source-record identification,
group mapping and issue counts plus migration 0344 after the fresh evidence
capture. D4.5 below follows that current local reader shape; D1.11 must confirm
its safe-view columns before it can be considered for execution. This does not
assert migration 0344 or this application version is deployed or authorize its
deployment. Source-record issue-count work is included in full HTTP timing,
but not separately decomposed by D4.5's row-query probe.

## Executing roles and protocol

| Batch | Executing database role | Purpose |
| --- | --- | --- |
| D1 | `operations_migrate` | Privileged catalog/migration/definition metadata, including `catalog`. |
| D2 | `operations_migrate` | Existing statistics and relation/index/TOAST sizes; no maintenance or reset. |
| D3 | `operations_migrate` | Privileged scope/reference/integrity counts across a bounded sample; RLS must not hide a mismatched target. |
| D4 | `operations_app` | Runtime-role SQL probes and authenticated Operations GET requests whose application database role must also be `operations_app`. |
| D5 | `operations_migrate` | Aggregate lifecycle/receipt/sample distributions and existing statistics for capacity/retention proposals. |

Migration 0006 declares `operations_migrate BYPASSRLS` and runtime
`operations_app NOBYPASSRLS`. Actual role availability, grants, installed
definitions, application configuration and PostgreSQL version remain unverified.
Role names are deliberate: D3 is **not** a runtime-role scope test; D4 is
**not** a privileged integrity query. A privileged result cannot prove what a
runtime reader can see. Do not substitute an administrator for failed D4 access,
create a role, grant privileges or change production settings to make a check run.

For any later approved execution, use the [workspace helper guidance](../operations.md#shared-validation-helper)
and its private profiles. Do not print profile/environment/credential values.
Connect as the named role; do not silently switch a broader session into it.
Submit **each numbered statement body separately**, inside its batch's wrapper,
then roll back. D1/D2/D3/D5 use this privileged wrapper. D4 uses the separate
application wrapper below. Session-local timeouts/GUCs are not persistent settings:

```sql
BEGIN TRANSACTION READ ONLY;
SET LOCAL search_path = pg_catalog;
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '5s';
SET LOCAL idle_in_transaction_session_timeout = '10s';
SET LOCAL operations.tenant_id = '1';
-- One numbered query body from this document.
ROLLBACK;
```

For **D4 only**, use the configured application search path, corroborated in
`operations/config/settings/prod.py`, rather than the privileged wrapper:

```sql
BEGIN TRANSACTION READ ONLY;
SET LOCAL search_path = operations, public;
SET LOCAL lock_timeout = '1s';
SET LOCAL statement_timeout = '15s';
SET LOCAL idle_in_transaction_session_timeout = '10s';
SET LOCAL operations.tenant_id = '1';
-- P0 or one numbered D4 query body.
ROLLBACK;
```

D4's P0 and plain plans use this same wrapper. Before considering execution,
confirm the installed application uses this path and operations_app; if it
differs, stop and review the draft rather than changing the application or
silently substituting a search path. Search-path parity does not prove parity
for every other connection setting. SQL bodies remain explicitly qualified.

Run P0 on each connection before other statements; the executor must assert
the exact role above, read-only = on, PostgreSQL major version 16, and for D3
superuser or BYPASSRLS. For D4 both privilege flags must be false. A mismatch,
missing relation, denied grant, timeout or query error stops that batch; record
the gap instead of changing roles/schema or expanding limits. D1 relation and
definition reconciliation precedes data queries; changed installed columns or
unreviewed function/view behavior require another static query review.
The Django ledger is the one explicit schema alternative: current production
settings declare search_path=operations,public, but older installations may
retain a public ledger. Discover both, query only an existing accessible ledger
with the exact alternatives below, and report both separately if both exist.
If neither exists, stop that ledger sub-batch; never silently merge their histories.

```sql
-- P0: role/version/transaction preflight; metadata only.
SELECT current_user AS executing_role,
       current_setting('server_version_num')::integer AS server_version_num,
       current_setting('transaction_read_only') AS transaction_read_only,
       current_setting('operations.tenant_id', true) AS tenant_context,
       current_setting('search_path') AS executing_search_path,
       r.rolsuper, r.rolbypassrls
FROM pg_catalog.pg_roles r
WHERE r.rolname = current_user;
```

Client execution contract: one connection/query at a time; D1/D2/D3/D5 have
a 30-second total wall budget each, with cancellation/rollback on expiry and
no automatic retries. D1 metadata bodies return at most 1,000 rows each and
at most 10,000 rows total; a body reaching its LIMIT is incomplete coverage,
not a full census. Bounded continuation text must be reviewed rather than
raising the cap. Query output retention is aggregate data and schema metadata
only: never row IDs, names, payloads, errors, source URLs or operator identities.

D4 has its own per-query/request bounds below. These bounds are engineering
proposals, not agreed service levels. No EXPLAIN ANALYZE, export, request or
source API call is implicitly included in another batch's approval.

Approval structure: **A = D1/D2/D5**, **B = D3 plain plans, then SELECTs only
if those plans pass review**, **C = D4 SQL/application load**. These are separate
choices; declining C does not block A. D1 precedes dependent B/C queries. None
is authorized by this document. See the [approval-request draft](PLAN-017-approval-request-draft.md).

## D1 — Catalog and definition reconciliation

These are exact initial query bodies, not a reconstruction of applied history.
Function/view definition digests identify change between captures but do not
alone prove semantic equality to source. No function bodies or config values
are returned. Catalog object names/DDL metadata are not customer rows.

```sql
-- D1.1: expected objects/SELECT privileges. Missing/denied objects stop dependent bodies.
SELECT target.name,
       pg_catalog.to_regclass(target.name) IS NOT NULL AS object_exists,
       CASE WHEN pg_catalog.to_regclass(target.name) IS NOT NULL
            THEN pg_catalog.has_table_privilege(current_user, target.name, 'SELECT')
            ELSE false END AS can_select
FROM unnest(ARRAY[
 'operations.django_migrations', 'public.django_migrations', 'ninja_core.schema_migrations',
 'operations.entity_observation_current', 'operations.entity_observation_history',
 'operations.observation_snapshot_runs', 'operations.source_record_seen_daily',
 'operations.source_bindings', 'operations.source_instances',
 'operations.devices', 'operations.clients', 'operations.v_device',
 'operations.v_entity_observation_admin_metadata', 'operations.source_health_current',
 'operations.v_client_source_mapping_effective', 'operations.entity_candidates',
 'operations.operator_job_runs', 'operations.source_refresh_outputs',
 'operations.software_installations_current', 'operations.software_installation_history',
 'operations.software_reclassification_targets', 'operations.device_requirement_state_drift',
 'operations.entity_attribute_effective_dirty', 'operations.entity_attribute_claim_history',
 'operations.run_log', 'catalog.publishers', 'catalog.products',
 'catalog.software_versions', 'catalog.capability_assertion_machine',
 'catalog.capability_assertion_operator', 'catalog.category_assertion_machine',
 'catalog.category_assertion_operator'
]::text[]) AS target(name)
ORDER BY target.name;

-- D1.2: relation kinds, scope flags and view definition digests.
SELECT n.nspname AS schema_name, c.relname AS object_name, c.relkind,
       c.relrowsecurity, c.relforcerowsecurity,
       CASE WHEN c.relkind IN ('v', 'm')
            THEN md5(pg_catalog.pg_get_viewdef(c.oid, true)) END AS view_definition_digest
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = ANY(ARRAY['operations','catalog','intel','ninja_core',
 'ninja_inventory','ninja_patches','ninja_activities','ninja_agent_compliance','public'])
  AND c.relkind IN ('r','p','v','m')
ORDER BY n.nspname, c.relname
LIMIT 1000;

-- D1.3: index definitions, validity and uniqueness; retain enforcing purpose.
SELECT n.nspname AS schema_name, tab.relname AS relation_name,
       idx.relname AS index_name, am.amname,
       i.indisprimary, i.indisunique, i.indisvalid, i.indisready,
       pg_catalog.pg_get_indexdef(idx.oid) AS index_definition
FROM pg_catalog.pg_index i
JOIN pg_catalog.pg_class tab ON tab.oid = i.indrelid
JOIN pg_catalog.pg_namespace n ON n.oid = tab.relnamespace
JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
JOIN pg_catalog.pg_am am ON am.oid = idx.relam
WHERE n.nspname = ANY(ARRAY['operations','catalog','intel','ninja_core',
 'ninja_inventory','ninja_patches','ninja_activities','ninja_agent_compliance'])
ORDER BY n.nspname, tab.relname, idx.relname
LIMIT 1000;

-- D1.4: constraints. Definition is schema DDL, not table contents.
SELECT n.nspname AS schema_name, c.relname AS relation_name,
       con.conname, con.contype, con.convalidated, con.condeferrable, con.condeferred,
       pg_catalog.pg_get_constraintdef(con.oid, true) AS constraint_definition
FROM pg_catalog.pg_constraint con
JOIN pg_catalog.pg_class c ON c.oid = con.conrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = ANY(ARRAY['operations','catalog','intel','ninja_core',
 'ninja_inventory','ninja_patches','ninja_activities','ninja_agent_compliance'])
ORDER BY n.nspname, c.relname, con.conname
LIMIT 1000;

-- D1.5: explicit triggers and function identities; FK internals are in D1.4.
SELECT n.nspname AS schema_name, c.relname AS relation_name, t.tgname,
       t.tgenabled, t.tgdeferrable, t.tginitdeferred,
       pn.nspname AS function_schema, p.proname AS function_name,
       pg_catalog.pg_get_function_identity_arguments(p.oid) AS function_arguments
FROM pg_catalog.pg_trigger t
JOIN pg_catalog.pg_class c ON c.oid = t.tgrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
JOIN pg_catalog.pg_proc p ON p.oid = t.tgfoid
JOIN pg_catalog.pg_namespace pn ON pn.oid = p.pronamespace
WHERE NOT t.tgisinternal
  AND n.nspname = ANY(ARRAY['operations','catalog','intel','ninja_core',
 'ninja_inventory','ninja_patches','ninja_activities','ninja_agent_compliance'])
ORDER BY n.nspname, c.relname, t.tgname
LIMIT 1000;

-- D1.6: direct view/matview relation dependencies, including catalog.
SELECT DISTINCT sn.nspname AS reader_schema, src.relname AS reader_name,
       tn.nspname AS input_schema, target.relname AS input_name, d.deptype
FROM pg_catalog.pg_rewrite rewrite
JOIN pg_catalog.pg_class src ON src.oid = rewrite.ev_class
JOIN pg_catalog.pg_namespace sn ON sn.oid = src.relnamespace
JOIN pg_catalog.pg_depend d ON d.classid = 'pg_catalog.pg_rewrite'::regclass
                          AND d.objid = rewrite.oid
                          AND d.refclassid = 'pg_catalog.pg_class'::regclass
JOIN pg_catalog.pg_class target ON target.oid = d.refobjid
JOIN pg_catalog.pg_namespace tn ON tn.oid = target.relnamespace
WHERE src.oid <> target.oid AND src.relkind IN ('v','m')
  AND sn.nspname = ANY(ARRAY['operations','catalog','intel','ninja_core',
 'ninja_inventory','ninja_patches','ninja_activities','ninja_agent_compliance'])
ORDER BY sn.nspname, src.relname, tn.nspname, target.relname, d.deptype
LIMIT 1000;

-- D1.7: policy shape/role OIDs, not arbitrary policy literals or source config.
SELECT n.nspname AS schema_name, c.relname AS relation_name, pol.polname,
       pol.polcmd, pol.polpermissive, pol.polroles,
       pol.polqual IS NOT NULL AS has_using,
       pol.polwithcheck IS NOT NULL AS has_check
FROM pg_catalog.pg_policy pol
JOIN pg_catalog.pg_class c ON c.oid = pol.polrelid
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = ANY(ARRAY['operations','catalog','intel','ninja_core',
 'ninja_inventory','ninja_patches','ninja_activities','ninja_agent_compliance'])
ORDER BY n.nspname, c.relname, pol.polname
LIMIT 1000;

-- D1.8: contract-function identity/security flags; no function bodies/config values.
SELECT n.nspname AS schema_name, p.proname,
       pg_catalog.pg_get_function_identity_arguments(p.oid) AS arguments,
       p.prosecdef, p.provolatile,
       EXISTS (SELECT 1 FROM unnest(p.proconfig) AS setting(value)
               WHERE setting.value LIKE 'search_path=%') AS has_pinned_search_path
FROM pg_catalog.pg_proc p
JOIN pg_catalog.pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'operations'
  AND p.proname = ANY(ARRAY['jobs_finish_v1','jobs_add_revision_dependency_v1',
   'refresh_derived','sync_entity_source_links_from_observations',
   'sync_entity_attribute_claims_from_observations','sync_entity_attribute_effective',
   'purge_closed_observation_history','purge_closed_attribute_claim_history',
   'merge_computers','split_computer_merge','write_device_requirement_state'])
ORDER BY p.proname, arguments
LIMIT 1000;

-- D1.9a: use if operations.django_migrations exists and is accessible.
SELECT app, count(*) AS migration_count, max(name) AS lexically_last_name
FROM operations.django_migrations WHERE app = 'operations' GROUP BY app;

-- D1.9b: use if public.django_migrations exists and is accessible.
SELECT app, count(*) AS migration_count, max(name) AS lexically_last_name
FROM public.django_migrations WHERE app = 'operations' GROUP BY app;

-- D1.10: ingest ledger. Separate statement, same per-statement wrapper.
SELECT count(*) AS migration_count, max(version) AS lexically_last_version
FROM ninja_core.schema_migrations;

-- D1.11: columns required by the current local Source-record reader, including 0344 additions.
SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type
FROM pg_catalog.pg_attribute a
WHERE a.attrelid = pg_catalog.to_regclass('operations.v_entity_observation_admin_metadata')
  AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY a.attnum
LIMIT 1000;
```

Ledger names/counts do not prove deployed application VERSION. A missing one of
the two Django alternatives is recorded, not treated as a missing domain table.

Gaps intentionally preserved: signatures/digests do not establish function-body
parity, caller reachability, external consumers, RLS predicate correctness or
deployed application VERSION. Follow-up definition retrieval must be limited to
reviewed object names and sanitized before retention. No hidden catalog dump,
function body, environment read or service request is part of D1.

## D2 — Statistics and physical sizes

Capture once; a second identical capture 15–60 minutes later is a separately
scheduled capture under the same explicit scope, never an unbounded polling
loop. Retain capture times and stats-reset times; counter differences across a
reset are invalid. Do not sum overlapping parent/index/TOAST totals or infer
exact populations or bloat from row estimates.

```sql
-- D2.1: per-relation estimates/counters/sizes; bounded metadata rows.
SELECT clock_timestamp() AS captured_at, n.nspname, c.relname, c.relkind,
       c.reltuples::bigint AS estimated_rows,
       pg_catalog.pg_relation_size(c.oid) AS main_bytes,
       pg_catalog.pg_total_relation_size(c.oid) AS total_bytes,
       CASE WHEN c.reltoastrelid <> 0
            THEN pg_catalog.pg_total_relation_size(c.reltoastrelid) ELSE 0 END AS toast_total_bytes,
       s.n_live_tup, s.n_dead_tup, s.n_tup_ins, s.n_tup_upd, s.n_tup_hot_upd,
       s.n_tup_del, s.last_vacuum, s.last_autovacuum, s.last_analyze, s.last_autoanalyze
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_catalog.pg_stat_all_tables s ON s.relid = c.oid
WHERE c.relkind IN ('r','p','m')
  AND n.nspname = ANY(ARRAY['operations','catalog','intel','ninja_core',
 'ninja_inventory','ninja_patches','ninja_activities','ninja_agent_compliance'])
ORDER BY n.nspname, c.relname
LIMIT 1000;

-- D2.2: index usage is relative to its reset/observation window, not a retirement proof.
SELECT clock_timestamp() AS captured_at, s.schemaname, s.relname, s.indexrelname,
       s.idx_scan, s.idx_tup_read, s.idx_tup_fetch,
       pg_catalog.pg_relation_size(s.indexrelid) AS index_bytes
FROM pg_catalog.pg_stat_user_indexes s
WHERE s.schemaname = ANY(ARRAY['operations','catalog','intel','ninja_core',
 'ninja_inventory','ninja_patches','ninja_activities','ninja_agent_compliance'])
ORDER BY s.schemaname, s.relname, s.indexrelname
LIMIT 1000;

-- D2.3: database counters, no database-name output.
SELECT clock_timestamp() AS captured_at, stats_reset,
       xact_commit, xact_rollback, blks_read, blks_hit, temp_files, temp_bytes,
       deadlocks, tup_inserted, tup_updated, tup_deleted
FROM pg_catalog.pg_stat_database WHERE datname = current_database();

-- D2.4: cluster-wide WAL, never attributed wholly to these tables/database.
SELECT clock_timestamp() AS captured_at, stats_reset,
       wal_records, wal_fpi, wal_bytes
FROM pg_catalog.pg_stat_wal;
```

## D3 — Privileged bounded integrity candidates

Executing role: **operations_migrate**, not operations_app. First review
`EXPLAIN (ANALYZE FALSE, FORMAT JSON)` of the exact SELECT bodies below, using
the same wrapper/role. Actual SELECT execution requires the reviewed plans to
fit the approved cost bounds. No repair/check-and-repair SQL functions are
called. Each sample is at most 5,000 keys; index-prefix samples are not random
or global proofs. All returned data are aggregate candidate counts. Scope
differences may represent unresolved business mappings rather than contamination.

```sql
-- D3.1: current/history consistency within a stable-key prefix sample.
WITH sample AS MATERIALIZED (
 SELECT observation_id, tenant_id, source_instance_id, external_namespace,
        parent_external_namespace, parent_external_id, external_id, active
 FROM operations.entity_observation_current ORDER BY observation_id LIMIT 5000
), measured AS (
 SELECT sample.*, (SELECT count(*) FROM operations.entity_observation_history h
   WHERE h.tenant_id = sample.tenant_id AND h.source_instance_id = sample.source_instance_id
     AND h.external_namespace = sample.external_namespace
     AND h.parent_external_namespace = sample.parent_external_namespace
     AND h.parent_external_id = sample.parent_external_id
     AND h.external_id = sample.external_id AND h.effective_to IS NULL) AS open_versions
 FROM sample
)
SELECT count(*) AS sampled, count(DISTINCT tenant_id) AS sampled_tenants,
       count(*) FILTER (WHERE open_versions <> CASE WHEN active THEN 1 ELSE 0 END) AS parity_candidates,
       count(*) FILTER (WHERE open_versions > 1) AS multiple_open_candidates
FROM measured;

-- D3.2: orphan/tenant/client candidates; joins by ID permit detecting hidden mismatches.
WITH sample AS MATERIALIZED (
 SELECT observation_id, tenant_id, source_binding_id, source_instance_id, device_id, client_id
 FROM operations.entity_observation_current ORDER BY observation_id LIMIT 5000
)
SELECT count(*) AS sampled,
 count(*) FILTER (WHERE sample.device_id IS NOT NULL AND d.id IS NULL) AS missing_device,
 count(*) FILTER (WHERE d.id IS NOT NULL AND d.tenant_id <> sample.tenant_id) AS device_tenant_mismatch,
 count(*) FILTER (WHERE sample.client_id IS NOT NULL AND c.id IS NULL) AS missing_client,
 count(*) FILTER (WHERE c.id IS NOT NULL AND c.tenant_id <> sample.tenant_id) AS client_tenant_mismatch,
 count(*) FILTER (WHERE d.id IS NOT NULL AND sample.client_id IS NOT NULL
                  AND d.client_id IS DISTINCT FROM sample.client_id) AS client_attribution_candidates,
 count(*) FILTER (WHERE binding.id IS NULL OR instance.id IS NULL) AS missing_source_reference,
 count(*) FILTER (WHERE binding.tenant_id <> sample.tenant_id
                  OR instance.tenant_id <> sample.tenant_id
                  OR binding.source_instance_id <> sample.source_instance_id) AS source_scope_candidates
FROM sample
LEFT JOIN operations.devices d ON d.id = sample.device_id
LEFT JOIN operations.clients c ON c.id = sample.client_id
LEFT JOIN operations.source_bindings binding ON binding.id = sample.source_binding_id
LEFT JOIN operations.source_instances instance ON instance.id = sample.source_instance_id;

-- D3.3: installation -> global catalog reference candidates.
WITH sample AS MATERIALIZED (
 SELECT tenant_id, software_version_id
 FROM operations.software_installations_current
 ORDER BY tenant_id, client_id, device_id, canonical_name LIMIT 5000
)
SELECT count(*) AS sampled,
 count(*) FILTER (WHERE sample.software_version_id IS NULL) AS unlinked,
 count(*) FILTER (WHERE sample.software_version_id IS NOT NULL AND v.id IS NULL) AS missing_version,
 count(*) FILTER (WHERE v.id IS NOT NULL AND p.id IS NULL) AS missing_product,
 count(*) FILTER (WHERE p.publisher_id IS NOT NULL AND publisher.id IS NULL) AS missing_publisher
FROM sample
LEFT JOIN catalog.software_versions v ON v.id = sample.software_version_id
LEFT JOIN catalog.products p ON p.id = v.product_id
LEFT JOIN catalog.publishers publisher ON publisher.id = p.publisher_id;

-- D3.4: daily-presence protected references, without retrieving any record IDs.
WITH sample AS MATERIALIZED (
 SELECT tenant_id, source_record_id, external_namespace, first_snapshot_run_id,
        backfilled_from_legacy
 FROM operations.source_record_seen_daily
 ORDER BY tenant_id, source_record_id, rollup_day LIMIT 5000
)
SELECT count(*) AS sampled,
 count(*) FILTER (WHERE c.observation_id IS NULL) AS missing_current,
 count(*) FILTER (WHERE c.tenant_id <> sample.tenant_id
                  OR c.external_namespace <> sample.external_namespace) AS current_scope_candidates,
 count(*) FILTER (WHERE sample.first_snapshot_run_id IS NOT NULL AND r.run_id IS NULL) AS missing_run,
 count(*) FILTER (WHERE r.tenant_id <> sample.tenant_id) AS run_tenant_mismatch,
 count(*) FILTER (WHERE (sample.backfilled_from_legacy AND sample.first_snapshot_run_id IS NOT NULL)
     OR (NOT sample.backfilled_from_legacy AND sample.first_snapshot_run_id IS NULL)) AS provenance_candidates
FROM sample
LEFT JOIN operations.entity_observation_current c ON c.observation_id = sample.source_record_id
LEFT JOIN operations.observation_snapshot_runs r ON r.run_id = sample.first_snapshot_run_id;

-- D3.5: completeness receipts; a candidate count needs source/accounting explanation.
WITH sample AS MATERIALIZED (
 SELECT status, is_complete_snapshot, expected_rows, written_rows, failed_rows,
        run_started_at, completed_at
 FROM operations.observation_snapshot_runs ORDER BY run_id LIMIT 5000
)
SELECT count(*) AS sampled,
 count(*) FILTER (WHERE status = 'complete' AND is_complete_snapshot IS TRUE
                   AND (failed_rows <> 0 OR expected_rows <> written_rows)) AS complete_count_candidates,
 count(*) FILTER (WHERE completed_at < run_started_at) AS time_order_candidates,
 count(*) FILTER (WHERE status = 'complete' AND is_complete_snapshot IS TRUE
                   AND expected_rows = 0 AND written_rows = 0) AS recorded_complete_empty
FROM sample;
```

```sql
-- D3.6: directly sample active Jobs via 0178's partial unique active-state index.
WITH jobs AS MATERIALIZED (
 SELECT status, requested_at, lease_expires_at
 FROM operations.operator_job_runs
 WHERE tenant_id = 1 AND status IN ('queued','running')
 ORDER BY job_key LIMIT 5000
), dirty AS MATERIALIZED (
 SELECT queued_at FROM operations.entity_attribute_effective_dirty
 ORDER BY queued_at, id LIMIT 5000
)
SELECT 'active_jobs_prefix' AS dataset, count(*) AS sampled,
 count(*) AS pending_in_sample,
 min(requested_at) AS oldest_pending_in_sample,
 count(*) FILTER (WHERE status = 'running' AND lease_expires_at < now()) AS expired_lease_candidates
FROM jobs
UNION ALL
SELECT 'effective_dirty_prefix', count(*), count(*), min(queued_at), NULL::bigint
FROM dirty;

-- D3.7: existing verdict-drift records, not a recomputation/repair function.
WITH sample AS MATERIALIZED (
 SELECT last_found_at FROM operations.device_requirement_state_drift
 WHERE cleared_at IS NULL ORDER BY id LIMIT 5000
)
SELECT count(*) AS sampled_open_drift_records,
 count(*) FILTER (WHERE last_found_at >= now() - interval '24 hours') AS recorded_within_24h,
 min(last_found_at) AS sample_oldest_last_found
FROM sample;
```

D3.6 uses `uq_operator_job_runs_active (tenant_id, job_key)` with its exact
queued/running predicate, not a sample dominated by terminal Jobs. A count below
5,000 describes matching rows at that statement snapshot; 5,000 is a lower
bound, not full depth. Job-key order does not prove the globally oldest active
Job when capped. The dirty-work sample remains separate. Plain plans must
confirm usable installed indexes and affordable access before SELECTs.

## D4 — Runtime-role query and full-request timings

Executing SQL role: **operations_app**, with the D4 application wrapper above.
Use the same runtime role through
the configured application for HTTP measurements; privileged SQL is not a
fallback. P0 must show no superuser/BYPASSRLS and tenant context 1. SQL bodies
below set a 15-second statement timeout in their individual read-only wrapper;
each is a separate at-most-30-second wall sub-batch. Review plain EXPLAIN
(ANALYZE FALSE) first. The ANALYZE statements below are explicit future work,
not included in permission for D1–D3 or executed by this assessment.

```sql
-- D4.1: aggregate preflight for export eligibility; no page payloads.
SELECT (SELECT count(*) FROM operations.v_device
         WHERE tenant_id = 1 AND lifecycle_status <> 'retired') AS current_computers,
       (SELECT count(*) FROM operations.v_entity_observation_admin_metadata
         WHERE tenant_id = 1) AS source_records;

-- D4.2: Computer population kernel, not the full Computers request.
SET LOCAL statement_timeout = '15s';
EXPLAIN (ANALYZE TRUE, BUFFERS TRUE, TIMING TRUE, FORMAT JSON)
SELECT count(*) FROM operations.v_device
WHERE tenant_id = 1 AND lifecycle_status <> 'retired';

-- D4.3: Source-record count, separately from ordering/choice discovery.
SET LOCAL statement_timeout = '15s';
EXPLAIN (ANALYZE TRUE, BUFFERS TRUE, TIMING TRUE, FORMAT JSON)
SELECT count(*) FROM operations.v_entity_observation_admin_metadata observation
WHERE observation.tenant_id = 1;

-- D4.4: Source-record type choices; source/client labels are measured by requests.
SET LOCAL statement_timeout = '15s';
EXPLAIN (ANALYZE TRUE, BUFFERS TRUE, TIMING TRUE, FORMAT JSON)
SELECT DISTINCT entity_type FROM operations.v_entity_observation_admin_metadata
WHERE tenant_id = 1 ORDER BY entity_type;

-- D4.4b: source filter choices, independently of record count/order.
SET LOCAL statement_timeout = '15s';
EXPLAIN (ANALYZE TRUE, BUFFERS TRUE, TIMING TRUE, FORMAT JSON)
SELECT instance.id, source.name, client.display_name
FROM operations.source_instances instance
JOIN operations.sources source ON source.id = instance.source_id
LEFT JOIN operations.clients client
 ON client.id = instance.client_id AND client.tenant_id = instance.tenant_id
WHERE instance.tenant_id = 1
ORDER BY source.name, client.display_name NULLS FIRST;

-- D4.4c: client filter choices, no returned client rows in EXPLAIN output.
SET LOCAL statement_timeout = '15s';
EXPLAIN (ANALYZE TRUE, BUFFERS TRUE, TIMING TRUE, FORMAT JSON)
SELECT id, slug, display_name FROM operations.clients
WHERE tenant_id = 1 AND deleted_at IS NULL ORDER BY display_name;

-- D4.5: unfiltered first Source-record page; plans expose no result-row values.
SET LOCAL statement_timeout = '15s';
EXPLAIN (ANALYZE TRUE, BUFFERS TRUE, TIMING TRUE, FORMAT JSON)
SELECT observation.observation_id, source.name, observation.entity_type,
 observation.external_id, observation.parent_external_id, observation.active,
 observation.observed_at, observation.last_seen_at, observation.withdrawn_at,
 observation.device_id, device.canonical_hostname, client.slug, client.display_name,
 observation.device_id IS NOT NULL AS has_computer,
 observation.client_id IS NOT NULL AS has_client,
 NULLIF(observation.parent_external_id, '') IS NOT NULL AS has_parent,
 observation.reported_name, observation.platform_group_id,
 observation.link_verdict, observation.archived,
 observation.source_layout, observation.source_url,
 device.entity_id, group_mapping.observed_name,
 EXISTS (SELECT 1 FROM operations.entity_candidates candidate
   WHERE candidate.tenant_id = observation.tenant_id
     AND candidate.source_instance_id = observation.source_instance_id
     AND candidate.external_id = observation.external_id
     AND candidate.status IN ('observed_only','pending')
     AND candidate.proposed_entity_class_id <> 'device') AS proposed_other
FROM operations.v_entity_observation_admin_metadata observation
JOIN operations.source_instances instance
 ON instance.tenant_id = observation.tenant_id AND instance.id = observation.source_instance_id
JOIN operations.sources source ON source.id = instance.source_id
LEFT JOIN operations.devices device
 ON device.tenant_id = observation.tenant_id AND device.id = observation.device_id
LEFT JOIN operations.clients client
 ON client.tenant_id = observation.tenant_id AND client.id = observation.client_id
LEFT JOIN operations.v_client_source_mapping_effective group_mapping
 ON group_mapping.tenant_id = observation.tenant_id
 AND group_mapping.source_id = instance.source_id
 AND group_mapping.external_id = observation.platform_group_id
WHERE observation.tenant_id = 1
ORDER BY observation.last_seen_at DESC NULLS LAST, observation.observation_id
LIMIT 100;

```

D4.S is **removed**, along with both client-filter HTTP probes. No client ID or
slug is selected for request binding; per-client scope/filter parity remains a
coverage gap. D4.4b/c remain EXPLAIN-only probes, not result-row retrieval.

**Part C owner: Claude in a new session**, per Point 38 / round 19 and the
user's subsequent direction. Use minimal metrics-only commands, not a general
executor or a manual-browser assignment to the user. Review/show each command
and its output contract before production use; obtain the confirmation specified
in the handoff. Commands must emit only allowlisted metrics, never page/CSV
contents, customer identifiers, source URLs, cookies, credentials or raw errors.

Use the approved workspace helper/private profiles. Establish privately whether
an operations_app database path and an authenticated Operations HTTP path exist.
If either is missing, stop and report the gap; do not substitute privileged SQL,
request pasted secrets, create sessions by other means or widen scope. The old
manual login/browser procedure is superseded; no authentication fallback is
implicitly authorized by moving C to Claude. Existing request/session/access
bookkeeping remains a disclosed application-load effect.

Exact measured HTTP request shapes (GET only after the stated authentication),
same approved identity/tenant. Execute in this order, with Computers CSV last;
no other route/parameter expansion:

```text
GET /inventory/computers/
GET /inventory/computers/?platform=Ninja
GET /inventory/computers/?computer_scope=any_online
GET /inventory/computers/?computer_scope=missing_required
GET /inventory/computers/?page=2
GET /inventory/source-records/
GET /inventory/source-records/?state=active
GET /inventory/source-records/?relationship=attached_computer
GET /inventory/source-records/?page=2
GET /inventory/source-records/?format=csv
GET /inventory/clients/
GET /patching/
GET /software/
GET /admin/jobs/
GET /inventory/computers/?format=csv
```

Request limits (revised 2026-10-25 after the first C run, which stopped when
`/software/` exceeded the original 15-second deadline; user direction: make
the rules more reasonable). One execution of each listed shape; the two
unfiltered HTML inventory routes may have two additional sequential
repetitions; a shape that breached or failed may be **re-measured once**, but
only after the server is confirmed to have finished the earlier request (its
access-log entry, or a worker-timeout record). Never re-send while completion
is unknown. At most 25 measured requests, one active at a time, total
diagnostic wall budget 20 minutes after authentication. HTML client deadline
**90 seconds**/8 MiB; CSV client deadline **120 seconds**/32 MiB and **50,000
complete data rows per export**. Gunicorn's worker timeout
(`OPERATIONS_TIMEOUT`, default 60 s) may end a request first; record that as a
server-side timeout, not a client breach. Permit each CSV only if D4.1 shows
its population <=50,000 and the D4 SQL probes passed. Computers CSV runs last
and additionally requires no unresolved breach and at least its full deadline
remaining in the budget. The earlier condition that every HTML request finish
in under 5.0 seconds is removed: a slow HTML page is a finding to report, not
a reason to skip the CSV measurement. The compact HTML and complete-detail CSV
paths differ; HTML speed does not establish CSV cost. Record any skip as
incomplete coverage. No partial export is counted as complete validation. A
client deadline or byte cap does not guarantee the server stopped, so stop the
request batch on breach and confirm completion before any re-measurement.

Keep response bodies inside the measurement command, away from agent-visible
stdout/stderr, logs and repository files. Discard HTML after extracting any
reviewed numeric metrics; count CSV data records with a streaming CSV parser
that handles quoted embedded newlines, excluding the header. A physical line
count alone is not a complete CSV record count. No body/CSV/headers or raw
exception may reach tool output. Prefer no sensitive temporary files; clean up
any unavoidable private temporary data on success or failure. A transfer-only
null sink cannot establish row counts/parity: report those as unknown unless
measured by a reviewed private extraction step.
Return only the public route shape, status, bytes, first/full response timings,
reviewed numeric counts, completion/limit and parity flags, plus approved SQL
plan cost/time numbers. Missing metrics remain unknown, never fabricated. Report
only generic error categories; suppress private URLs/parameters and raw errors.
Check that cards/filter links use the listed matching scope before following
them; an unlisted destination is a gap requiring a reviewed addition. No new
instrumentation, forced cache flush, service restart, API-source call or write
endpoint is included. Existing application request handling may update session/
access bookkeeping; this application-load scope is distinct from read-only SQL.

Record role, tenant, capture/deployment date, population, repetitions and cache
condition. SQL execution/buffers are separate probes, not a full decomposition
of the web request. Transfer/render/Python costs remain unknown where existing
instrumentation cannot separate them without a runtime change. Covering these
representative domain pages does not establish all filter/export variants.

The [former H2 human procedure](PLAN-017-D4-human-measurement.md) is retained
as superseded history, not a task for the user. Point 38 governs C execution.
Retain its numeric Computers CSV gate, including at least 30 seconds left in
the total budget. CLI timings/cache conditions are not browser DevTools or
render timings; report the actual measurement method and any resulting gaps.
Record metrics only in `docs/records/PLAN-017-d4-results.md` after execution.

## D5 — Retention, references, growth and receipt distributions

Executing role: operations_migrate. Include `catalog` in scope. Use D2's two
size/counter snapshots for observed growth; row estimates and prefix samples
cannot establish population-wide churn/retention rates. The age bins below are
diagnostic sensitivity bins, not adoption of a retention or undo horizon.

```sql
-- D5.1: bounded closed/open observation-history age distribution; no row IDs/data.
WITH sample AS MATERIALIZED (
 SELECT effective_from, effective_to
 FROM operations.entity_observation_history ORDER BY id LIMIT 5000
)
SELECT count(*) AS sampled,
 count(*) FILTER (WHERE effective_to IS NULL) AS open_rows,
 count(*) FILTER (WHERE effective_to < now() - interval '30 days') AS closed_over_30d,
 count(*) FILTER (WHERE effective_to < now() - interval '90 days') AS closed_over_90d,
 count(*) FILTER (WHERE effective_to < now() - interval '365 days') AS closed_over_365d,
 min(effective_from) AS sample_first_interval,
 max(effective_to) AS sample_last_close
FROM sample;

-- D5.2: uncapped 30-day aggregate, platform only; never output full client-bearing kind.
SELECT split_part(kind, '.', 2) AS platform,
 count(*) AS source_receipts_30d,
 count(*) FILTER (WHERE ok IS TRUE AND rows = 0) AS source_ok_zero,
 count(*) FILTER (WHERE ok IS FALSE) AS source_failed,
 min(started_at) AS window_started_min, max(ended_at) AS window_ended_max
FROM operations.run_log
WHERE tenant_id = 1 AND kind LIKE 'source.%'
  AND started_at >= now() - interval '30 days' AND started_at < now()
GROUP BY split_part(kind, '.', 2)
ORDER BY platform;

-- D5.3: pending software demand sample, no title/key/source output.
WITH sample AS MATERIALIZED (
 SELECT queued_at
 FROM operations.software_reclassification_targets
 WHERE tenant_id = 1 AND consumed_at IS NULL
 ORDER BY queued_at LIMIT 5000
)
SELECT count(*) AS sampled,
 count(*) AS sampled_pending,
 min(queued_at) AS sample_oldest_pending,
 max(queued_at) AS sample_newest_pending
FROM sample;

-- D5.4: reference/operator episode sample, protected state distinct from feed bytes.
WITH machine AS MATERIALIZED (
 SELECT withdrawn_at FROM catalog.capability_assertion_machine ORDER BY id LIMIT 5000
), authored AS MATERIALIZED (
 SELECT withdrawn_at FROM catalog.capability_assertion_operator ORDER BY id LIMIT 5000
)
SELECT 'capability_machine' AS dataset, count(*) AS sampled,
       count(*) FILTER (WHERE withdrawn_at IS NULL) AS current_rows,
       count(*) FILTER (WHERE withdrawn_at IS NOT NULL) AS closed_episodes
FROM machine
UNION ALL
SELECT 'capability_operator', count(*),
       count(*) FILTER (WHERE withdrawn_at IS NULL),
       count(*) FILTER (WHERE withdrawn_at IS NOT NULL)
FROM authored;

-- D5.5: existing column statistics only, excluding value histograms/most-common values.
SELECT schemaname, tablename, attname, null_frac, avg_width, n_distinct, correlation
FROM pg_catalog.pg_stats
WHERE schemaname = ANY(ARRAY['operations','catalog','intel','ninja_core',
 'ninja_inventory','ninja_patches','ninja_activities','ninja_agent_compliance'])
  AND attname = ANY(ARRAY['raw_data','canonical_data','material_data','raw_nvd',
   'observed_at','last_seen_at','effective_from','effective_to','rollup_day',
   'withdrawn_at','queued_at','consumed_at'])
ORDER BY schemaname, tablename, attname
LIMIT 1000;
```

D5.2 requires a plain EXPLAIN of that exact body before its SELECT, within A's
D5 budget. Verify `idx_run_log_kind_started (tenant_id, kind, started_at)` is
installed/valid in D1 and the plan actually uses affordable index-backed access.
LIKE selectivity/collation and a range on the third index key do not guarantee
a cheap plan. Stop this sub-batch for a broad scan/sort or uncertain cost;
do not force planner settings, add indexes or silently widen the window.
This aggregates **all matching source receipts within 30 days**, with no input
or output LIMIT and no kind/time prefix sampling. The 5-second statement and
30-second batch timeouts bound execution; a timeout yields no complete result,
not partial counts. A shorter window needs separately reviewed exact text;
do not silently retry or change the interval. Only `split_part(kind, '.', 2)`
is grouped/returned: full kind embeds per-client source_key and must never be
printed, grouped for output or added to evidence. The plan may mention the
generic source-prefix predicate, not customer-bearing kind values. Zero-row
success is a candidate, not proof acquisition was incorrectly incomplete.
D5.3 directly uses 0250's pending `(tenant_id, queued_at)` partial-index state;
review its plain plan too. Fewer than 5,000 rows gives snapshot pending depth,
while 5,000 is a lower bound; queue age is measured within that pending sample.
No completed-target history is scanned or inferred from this query.

D5 cannot establish full raw-payload fidelity, original transport bytes,
historical source availability, complete disposal enforcement or costed N/time/
hybrid guarantees from these samples. No payload-width scan, full-table count,
log-content scan, source API request or reference refresh is hidden in this
batch. Those gaps retain explicit verification destinations in the gate ledger.

## Static validation and release boundary

These statements were drafted against pinned local source declarations only.
Role/column/function availability, SQL parse/plans/cost, HTTP behavior and
installed-definition parity have not been validated against a running server.
Review must resolve cost and coverage limitations before any approval request.
No commit, push, release metadata change, migration or deployment is proposed.
