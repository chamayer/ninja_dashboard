"""Seed and activate the ADR-0010 delta-only attribute claim projector.

Migration 0102 creates the additive tables. This migration installs contracts,
tenant constraints, RLS, redacted reads, and bounded projector functions. It
does not run the projector: ingest starts bounded backfill only after Django
has committed both migrations, avoiding DDL/backfill lock overlap.
"""

from django.db import migrations

SCHEMA_INDEX_SQL = r"""
CREATE UNIQUE INDEX IF NOT EXISTS
    uq_obs_current_tenant_observation_idx
    ON operations.entity_observation_current (tenant_id, observation_id);
"""

ATTRIBUTE_CONTRACT_SQL = r"""
ALTER TABLE operations.entity_observation_current
    ADD CONSTRAINT uq_obs_current_tenant_observation
    UNIQUE USING INDEX uq_obs_current_tenant_observation_idx;
ALTER TABLE operations.entity_source_links
    ADD CONSTRAINT uq_entity_source_links_tenant_id UNIQUE (tenant_id, id);

ALTER TABLE operations.identity_authority_policies
    ADD CONSTRAINT fk_identity_policy_tenant_source
    FOREIGN KEY (tenant_id, source_instance_id)
    REFERENCES operations.source_instances (tenant_id, id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;
ALTER TABLE operations.attribute_authority_policies
    ADD CONSTRAINT fk_attr_policy_tenant_source
    FOREIGN KEY (tenant_id, source_instance_id)
    REFERENCES operations.source_instances (tenant_id, id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_attribute_claim_current
    ADD CONSTRAINT fk_attr_claim_tenant_entity_class
    FOREIGN KEY (tenant_id, entity_id, entity_class_id)
    REFERENCES operations.entities (tenant_id, id, entity_class_id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_claim_tenant_observation
    FOREIGN KEY (tenant_id, observation_id)
    REFERENCES operations.entity_observation_current (tenant_id, observation_id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_claim_tenant_source
    FOREIGN KEY (tenant_id, source_instance_id)
    REFERENCES operations.source_instances (tenant_id, id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_claim_tenant_value_entity
    FOREIGN KEY (tenant_id, value_entity_id)
    REFERENCES operations.entities (tenant_id, id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_claim_definition_type
    FOREIGN KEY (attribute_definition_id, value_type, cardinality)
    REFERENCES operations.attribute_definitions (id, value_type, cardinality)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_attribute_claim_history
    ADD CONSTRAINT fk_attr_hist_tenant_current
    FOREIGN KEY (tenant_id, current_claim_id)
    REFERENCES operations.entity_attribute_claim_current (tenant_id, id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_hist_tenant_entity_class
    FOREIGN KEY (tenant_id, entity_id, entity_class_id)
    REFERENCES operations.entities (tenant_id, id, entity_class_id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_hist_tenant_observation
    FOREIGN KEY (tenant_id, observation_id)
    REFERENCES operations.entity_observation_current (tenant_id, observation_id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_hist_tenant_source
    FOREIGN KEY (tenant_id, source_instance_id)
    REFERENCES operations.source_instances (tenant_id, id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_hist_tenant_value_entity
    FOREIGN KEY (tenant_id, value_entity_id)
    REFERENCES operations.entities (tenant_id, id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_hist_definition_type
    FOREIGN KEY (attribute_definition_id, value_type, cardinality)
    REFERENCES operations.attribute_definitions (id, value_type, cardinality)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_attribute_withheld_current
    ADD CONSTRAINT fk_attr_withheld_tenant_observation
    FOREIGN KEY (tenant_id, observation_id)
    REFERENCES operations.entity_observation_current (tenant_id, observation_id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_withheld_tenant_source
    FOREIGN KEY (tenant_id, source_instance_id)
    REFERENCES operations.source_instances (tenant_id, id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

ALTER TABLE operations.entity_attribute_projection_state
    ADD CONSTRAINT fk_attr_state_tenant_observation
    FOREIGN KEY (tenant_id, observation_id)
    REFERENCES operations.entity_observation_current (tenant_id, observation_id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_state_tenant_source
    FOREIGN KEY (tenant_id, source_instance_id)
    REFERENCES operations.source_instances (tenant_id, id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_state_tenant_link
    FOREIGN KEY (tenant_id, entity_source_link_id)
    REFERENCES operations.entity_source_links (tenant_id, id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED,
    ADD CONSTRAINT fk_attr_state_tenant_entity
    FOREIGN KEY (tenant_id, entity_id)
    REFERENCES operations.entities (tenant_id, id)
    ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX IF NOT EXISTS idx_attr_claim_history_brin
    ON operations.entity_attribute_claim_history
    USING brin (effective_from, effective_to);

INSERT INTO operations.attribute_definitions (
    entity_class_id, key, display_name, description, value_type, cardinality,
    sensitivity, validation, canonical_projection_eligible,
    single_value_conflict_policy, set_merge_policy, definition_version, enabled
)
SELECT entity_class_id, key, display_name, description, value_type, cardinality,
       sensitivity, '{}'::jsonb, canonical_projection_eligible,
       single_conflict, 'highest_authority_union', 1, TRUE
FROM (VALUES
    ('client','name','Name','Source-reported client or organization name.','text','single','internal',TRUE,'retain_last_uncontested'),
    ('client','normalized_name','Normalized name','Normalized source organization name.','text','single','internal',FALSE,'retain_last_uncontested'),
    ('client','source_device_count','Source device count','Devices reported in the source container.','number','single','internal',FALSE,'unknown'),
    ('client','source_placeholder','Placeholder container','Whether the source container is a configured placeholder.','boolean','single','internal',FALSE,'unknown'),
    ('device','hostname','Hostname','Source-reported device hostname.','text','single','internal',TRUE,'retain_last_uncontested'),
    ('device','serial_number','Serial number','Source-reported hardware serial.','text','single','sensitive',TRUE,'retain_last_uncontested'),
    ('device','mac_address','MAC address','Normalized source-reported MAC address.','text','set','sensitive',TRUE,'unknown'),
    ('device','vm_uuid','Virtual machine UUID','Source-reported virtual machine UUID.','text','single','sensitive',TRUE,'retain_last_uncontested'),
    ('device','is_virtual_machine','Virtual machine','Source-reported virtual-machine classification.','boolean','single','internal',TRUE,'unknown'),
    ('device','node_class','Native node class','Source-native device classification.','text','single','internal',FALSE,'unknown'),
    ('device','device_role','Device role','Normalized source-reported device role.','text','single','internal',TRUE,'retain_last_uncontested'),
    ('device','os_name','Operating system','Source-reported operating-system name.','text','single','internal',TRUE,'retain_last_uncontested'),
    ('device','os_family','Operating-system family','Normalized operating-system family.','text','single','internal',TRUE,'retain_last_uncontested'),
    ('device','domain','Domain','Source-reported device domain or DNS suffix.','text','single','sensitive',TRUE,'retain_last_uncontested'),
    ('device','is_online','Reported online state','Explicit source-reported online state.','boolean','single','internal',FALSE,'unknown'),
    ('device','offline','Reported offline state','Explicit source-reported offline state.','boolean','single','internal',FALSE,'unknown'),
    ('device','power_state','Hypervisor power state','Hypervisor-reported power-dimension measurement.','text','single','internal',FALSE,'unknown'),
    ('device','last_boot_time_at','OS boot time','Guest or host OS-reported boot time.','timestamp','single','internal',FALSE,'unknown'),
    ('device','hypervisor_reported_boot_time_at','Hypervisor boot time','Distinct hypervisor-reported boot measurement.','timestamp','single','internal',FALSE,'unknown'),
    ('device','needs_reboot','Needs reboot','Source-reported reboot requirement.','boolean','single','internal',FALSE,'unknown'),
    ('device','reboot_reason','Reboot reason','Source-reported reboot reason member.','text','set','internal',FALSE,'unknown'),
    ('device','last_user','Last user','Source-reported last logged-in user.','text','single','sensitive',FALSE,'unknown'),
    ('device','maintenance_status','Maintenance status','Source-reported maintenance state.','text','single','internal',FALSE,'unknown'),
    ('device','maintenance_start_at','Maintenance start','Source-reported maintenance start.','timestamp','single','internal',FALSE,'unknown'),
    ('device','maintenance_end_at','Maintenance end','Source-reported maintenance end.','timestamp','single','internal',FALSE,'unknown'),
    ('device','pending_reboot_reason','Pending reboot reason','Health endpoint reboot evidence.','text','single','internal',FALSE,'unknown'),
    ('device','failed_os_patches_count','Failed OS patches','Health endpoint count.','number','single','internal',FALSE,'unknown'),
    ('device','pending_os_patches_count','Pending OS patches','Health endpoint count.','number','single','internal',FALSE,'unknown'),
    ('device','failed_software_patches_count','Failed software patches','Health endpoint count.','number','single','internal',FALSE,'unknown'),
    ('device','pending_software_patches_count','Pending software patches','Health endpoint count.','number','single','internal',FALSE,'unknown'),
    ('device','alert_count','Alert count','Health endpoint count.','number','single','internal',FALSE,'unknown'),
    ('device','active_job_count','Active job count','Health endpoint count.','number','single','internal',FALSE,'unknown'),
    ('device','health_status','Health status','Source-reported health summary.','text','single','internal',FALSE,'unknown'),
    ('device','active_threats_count','Active threats','Health endpoint count.','number','single','internal',FALSE,'unknown'),
    ('device','quarantined_threats_count','Quarantined threats','Health endpoint count.','number','single','internal',FALSE,'unknown'),
    ('device','blocked_threats_count','Blocked threats','Health endpoint count.','number','single','internal',FALSE,'unknown'),
    ('device','critical_vulnerability_count','Critical vulnerabilities','Health endpoint count.','number','single','internal',FALSE,'unknown'),
    ('device','high_vulnerability_count','High vulnerabilities','Health endpoint count.','number','single','internal',FALSE,'unknown'),
    ('device','medium_vulnerability_count','Medium vulnerabilities','Health endpoint count.','number','single','internal',FALSE,'unknown'),
    ('device','low_vulnerability_count','Low vulnerabilities','Health endpoint count.','number','single','internal',FALSE,'unknown'),
    ('device','installation_issues_count','Installation issues','Health endpoint count.','number','single','internal',FALSE,'unknown'),
    ('device','parent_offline','Parent offline','Source-reported parent device state.','boolean','single','internal',FALSE,'unknown'),
    ('device','product_installation_status','Product installation status','Structured troubleshooting detail.','structured','single','restricted',FALSE,'unknown'),
    ('device','cmdb_layout_id','CMDB layout ID','Source-native CMDB layout identifier.','number','single','internal',FALSE,'unknown'),
    ('device','cmdb_layout','CMDB layout','Source-native CMDB layout name.','text','single','internal',FALSE,'unknown'),
    ('device','cmdb_url','CMDB URL','Source-native CMDB record URL.','text','single','restricted',FALSE,'unknown'),
    ('device','cmdb_archived','CMDB archived','Source-reported CMDB archive state.','boolean','single','internal',FALSE,'unknown'),
    ('device','cmdb_link_verdict','CMDB link verdict','Normalized CMDB relay/link status.','text','single','internal',FALSE,'unknown'),
    ('device','cmdb_provenance','CMDB provenance','Structured CMDB relay provenance.','structured','single','restricted',FALSE,'unknown'),
    ('device','cmdb_relayed','CMDB relayed','Whether CMDB evidence used a source relay.','boolean','single','internal',FALSE,'unknown')
) AS seed(entity_class_id, key, display_name, description, value_type,
          cardinality, sensitivity, canonical_projection_eligible,
          single_conflict)
ON CONFLICT (entity_class_id, key, definition_version) DO NOTHING;

INSERT INTO operations.source_field_mappings (
    source_id, external_namespace, native_record_type, document_kind,
    source_field, attribute_definition_id, mapping_version, enabled
)
SELECT NULL, '', '', 'canonical', mapping.source_field, definition.id, 1, TRUE
FROM (VALUES
    ('client','name','name'),
    ('client','normalized_name','normalized_name'),
    ('client','source_device_count','device_count'),
    ('client','source_placeholder','is_placeholder'),
    ('device','hostname','hostname'),
    ('device','serial_number','serial_number'),
    ('device','mac_address','macs'),
    ('device','vm_uuid','vm_uuid'),
    ('device','is_virtual_machine','is_vm'),
    ('device','node_class','node_class'),
    ('device','device_role','device_role'),
    ('device','os_name','os_name'),
    ('device','os_family','os_family'),
    ('device','domain','domain'),
    ('device','is_online','is_online'),
    ('device','offline','offline'),
    ('device','power_state','power_state'),
    ('device','last_boot_time_at','last_boot_time_at'),
    ('device','hypervisor_reported_boot_time_at','hypervisor_reported_boot_time_at'),
    ('device','needs_reboot','needs_reboot'),
    ('device','reboot_reason','needs_reboot_reasons'),
    ('device','last_user','last_user'),
    ('device','maintenance_status','maintenance_status'),
    ('device','maintenance_start_at','maintenance_start_at'),
    ('device','maintenance_end_at','maintenance_end_at'),
    ('device','pending_reboot_reason','pending_reboot_reason'),
    ('device','failed_os_patches_count','failed_os_patches_count'),
    ('device','pending_os_patches_count','pending_os_patches_count'),
    ('device','failed_software_patches_count','failed_software_patches_count'),
    ('device','pending_software_patches_count','pending_software_patches_count'),
    ('device','alert_count','alert_count'),
    ('device','active_job_count','active_job_count'),
    ('device','health_status','health_status'),
    ('device','active_threats_count','active_threats_count'),
    ('device','quarantined_threats_count','quarantined_threats_count'),
    ('device','blocked_threats_count','blocked_threats_count'),
    ('device','critical_vulnerability_count','critical_vulnerability_count'),
    ('device','high_vulnerability_count','high_vulnerability_count'),
    ('device','medium_vulnerability_count','medium_vulnerability_count'),
    ('device','low_vulnerability_count','low_vulnerability_count'),
    ('device','installation_issues_count','installation_issues_count'),
    ('device','parent_offline','parent_offline'),
    ('device','product_installation_status','products_installation_statuses'),
    ('device','cmdb_layout_id','hudu_layout_id'),
    ('device','cmdb_layout','hudu_layout'),
    ('device','cmdb_url','hudu_url'),
    ('device','cmdb_archived','archived'),
    ('device','cmdb_link_verdict','link_verdict'),
    ('device','cmdb_provenance','provenance'),
    ('device','cmdb_relayed','relayed')
) AS mapping(entity_class_id, attribute_key, source_field)
JOIN operations.attribute_definitions definition
  ON definition.entity_class_id = mapping.entity_class_id
 AND definition.key = mapping.attribute_key
 AND definition.enabled
ON CONFLICT (
    source_id, external_namespace, native_record_type, document_kind,
    source_field, mapping_version
) DO NOTHING;

INSERT INTO operations.identity_authority_policies (
    id, tenant_id, version, source_instance_id, native_record_type,
    resulting_entity_type_id, may_establish_identity, may_create_canonical,
    enabled, reason
)
SELECT gen_random_uuid(), observed.tenant_id, 1, observed.source_instance_id,
       observed.entity_type, entity_type.name,
       entity_type.is_identity_signal, entity_type.is_identity_signal, TRUE,
       'system.compatibility_backfill'
FROM (
    SELECT DISTINCT tenant_id, source_instance_id, entity_type
    FROM operations.entity_observation_current
) observed
JOIN operations.entity_types entity_type ON entity_type.name = observed.entity_type
ON CONFLICT (
    tenant_id, source_instance_id, native_record_type, resulting_entity_type_id
) DO NOTHING;

INSERT INTO operations.attribute_authority_policies (
    id, tenant_id, version, source_instance_id, native_record_type,
    attribute_definition_id, eligible, authority_tier, priority, enabled, reason
)
SELECT gen_random_uuid(), observed.tenant_id, 1, observed.source_instance_id,
       observed.entity_type, definition.id,
       observed.entity_type IN (
           'agent.rmm', 'agent.edr', 'agent.remote_access',
           'network.device', 'vm.host', 'vm.guest', 'monitor.target', 'org'
       ),
       CASE
         WHEN observed.entity_type = 'agent.rmm' THEN 300
         WHEN observed.entity_type = 'agent.edr' THEN 250
         WHEN observed.entity_type = 'agent.remote_access' THEN 225
         WHEN observed.entity_type = 'network.device' THEN 200
         WHEN observed.entity_type = 'vm.host' THEN 200
         WHEN observed.entity_type = 'vm.guest'
          AND definition.key IN ('power_state', 'hypervisor_reported_boot_time_at')
           THEN 300
         WHEN observed.entity_type = 'vm.guest' THEN 150
         WHEN observed.entity_type = 'monitor.target' THEN 100
         WHEN observed.entity_type = 'org' THEN 200
         WHEN observed.entity_type = 'cmdb.asset' THEN 50
         ELSE 0
       END,
       0, TRUE, 'system.compatibility_backfill'
FROM (
    SELECT DISTINCT o.tenant_id, o.source_instance_id, o.entity_type,
           COALESCE(link.entity_class_id, entity_type.entity_class_id)
               AS entity_class_id
    FROM operations.entity_observation_current o
    LEFT JOIN operations.entity_source_links link
      ON link.tenant_id = o.tenant_id
     AND link.source_instance_id = o.source_instance_id
     AND link.external_namespace = o.external_namespace
     AND link.parent_external_namespace = o.parent_external_namespace
     AND link.parent_external_id = o.parent_external_id
     AND link.external_id = o.external_id
    LEFT JOIN operations.entity_types entity_type
      ON entity_type.name = o.entity_type
) observed
JOIN operations.attribute_definitions definition
  ON definition.entity_class_id = observed.entity_class_id
 AND definition.enabled
WHERE EXISTS (
    SELECT 1
    FROM operations.source_field_mappings mapping
    WHERE mapping.attribute_definition_id = definition.id
      AND mapping.enabled
)
ON CONFLICT (
    tenant_id, source_instance_id, native_record_type, attribute_definition_id
) DO NOTHING;

-- The new tenant-safe foreign keys are initially deferred. Validate their
-- seed writes before the following table-level RLS/ownership DDL so PostgreSQL
-- has no pending constraint-trigger events during ALTER TABLE.
SET CONSTRAINTS ALL IMMEDIATE;

ALTER TABLE operations.identity_authority_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.identity_authority_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.attribute_authority_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.attribute_authority_policies FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_claim_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_claim_current FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_claim_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_claim_history FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_withheld_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_withheld_current FORCE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_projection_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE operations.entity_attribute_projection_state FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON operations.identity_authority_policies
    USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
CREATE POLICY tenant_isolation ON operations.attribute_authority_policies
    USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
CREATE POLICY tenant_isolation ON operations.entity_attribute_claim_current
    USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
CREATE POLICY tenant_isolation ON operations.entity_attribute_claim_history
    USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
CREATE POLICY tenant_isolation ON operations.entity_attribute_withheld_current
    USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
CREATE POLICY tenant_isolation ON operations.entity_attribute_projection_state
    USING (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint)
    WITH CHECK (tenant_id = current_setting('operations.tenant_id', TRUE)::bigint);
"""


PROJECTOR_SQL = r"""
CREATE OR REPLACE FUNCTION operations.current_tenant_id()
RETURNS bigint
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog
AS $function$
DECLARE
    value text;
    tenant_id bigint;
BEGIN
    value := current_setting('operations.tenant_id', TRUE);
    IF value IS NULL OR value = '' OR value !~ '^[0-9]+$' THEN
        RAISE EXCEPTION 'valid operations.tenant_id context is required'
            USING ERRCODE = '42501';
    END IF;
    tenant_id := value::bigint;
    IF tenant_id <= 0 THEN
        RAISE EXCEPTION 'positive operations.tenant_id context is required'
            USING ERRCODE = '42501';
    END IF;
    RETURN tenant_id;
END;
$function$;

CREATE OR REPLACE FUNCTION operations.try_claim_numeric(value text)
RETURNS numeric
LANGUAGE plpgsql
IMMUTABLE STRICT
SET search_path = pg_catalog
AS $function$
BEGIN
    RETURN value::numeric;
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$function$;

CREATE OR REPLACE FUNCTION operations.try_claim_timestamptz(value text)
RETURNS timestamptz
LANGUAGE plpgsql
IMMUTABLE STRICT
SET search_path = pg_catalog
AS $function$
BEGIN
    RETURN value::timestamptz;
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$function$;

CREATE OR REPLACE FUNCTION operations.try_claim_uuid(value text)
RETURNS uuid
LANGUAGE plpgsql
IMMUTABLE STRICT
SET search_path = pg_catalog
AS $function$
BEGIN
    RETURN value::uuid;
EXCEPTION WHEN OTHERS THEN
    RETURN NULL;
END;
$function$;

CREATE OR REPLACE FUNCTION operations.sync_entity_attribute_claims_from_observations(
    batch_size integer DEFAULT 500
)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE
    projection_contract constant integer := 1;
    projected_at timestamptz := clock_timestamp();
    batch_rows integer := 0;
    inserted_claims integer := 0;
    updated_claims integer := 0;
    withdrawn_claims integer := 0;
    inserted_history integer := 0;
    closed_history integer := 0;
    withheld_writes integer := 0;
BEGIN
    IF batch_size < 1 OR batch_size > 10000 THEN
        RAISE EXCEPTION 'batch_size must be between 1 and 10000';
    END IF;
    IF NOT pg_try_advisory_xact_lock(
        hashtextextended('operations.attribute_claim_projection', 0)
    ) THEN
        RETURN jsonb_build_object('status', 'busy', 'processed', 0);
    END IF;

    DROP TABLE IF EXISTS pg_temp.claim_projection_batch;
    CREATE TEMP TABLE claim_projection_batch ON COMMIT DROP AS
    WITH candidates AS (
        SELECT o.observation_id, o.tenant_id, o.source_instance_id,
               source_instance.source_id, o.external_namespace,
               o.parent_external_namespace, o.parent_external_id,
               o.external_id, o.entity_type, o.observed_at, o.last_received_at,
               o.active, o.withdrawn_at, o.raw_data, o.canonical_data,
               link.id AS entity_source_link_id, link.entity_id,
               COALESCE(link.entity_class_id, entity_type.entity_class_id)
                   AS classified_entity_class_id,
               pg_catalog.sha256(
                   o.material_hash || convert_to(
                   '|hash-algorithm:' || o.hash_algorithm_version::text
                   || '|material-projection:'
                   || o.material_projection_version::text
                   || '|source-schema:' || o.schema_version::text
                   || '|active:' || o.active::text
                   || '|link:' || COALESCE(link.id::text, '')
                   || '|entity:' || COALESCE(link.entity_id::text, '')
                   || '|type:' || o.entity_type
                   || '|class:' || COALESCE(
                       link.entity_class_id, entity_type.entity_class_id, ''
                   )
                   || '|contract:' || projection_contract::text,
                   'UTF8'
               )) AS projection_hash
        FROM entity_observation_current o
        JOIN source_instances source_instance
          ON source_instance.id = o.source_instance_id
         AND source_instance.tenant_id = o.tenant_id
        LEFT JOIN entity_source_links link
          ON link.tenant_id = o.tenant_id
         AND link.source_instance_id = o.source_instance_id
         AND link.external_namespace = o.external_namespace
         AND link.parent_external_namespace = o.parent_external_namespace
         AND link.parent_external_id = o.parent_external_id
         AND link.external_id = o.external_id
        LEFT JOIN entity_types entity_type ON entity_type.name = o.entity_type
    )
    SELECT candidate.*
    FROM candidates candidate
    LEFT JOIN entity_attribute_projection_state state
      ON state.tenant_id = candidate.tenant_id
     AND state.observation_id = candidate.observation_id
    WHERE state.observation_id IS NULL
       OR state.projection_hash IS DISTINCT FROM candidate.projection_hash
       OR state.observation_active IS DISTINCT FROM candidate.active
       OR state.entity_source_link_id IS DISTINCT FROM candidate.entity_source_link_id
       OR state.entity_id IS DISTINCT FROM candidate.entity_id
       OR state.projection_contract_version <> projection_contract
    ORDER BY candidate.tenant_id, candidate.observation_id
    LIMIT batch_size;
    GET DIAGNOSTICS batch_rows = ROW_COUNT;

    IF batch_rows = 0 THEN
        RETURN jsonb_build_object(
            'status', 'complete', 'processed', 0, 'inserted_claims', 0,
            'updated_claims', 0, 'withdrawn_claims', 0,
            'inserted_history', 0, 'closed_history', 0,
            'withheld_writes', 0
        );
    END IF;

    DROP TABLE IF EXISTS pg_temp.claim_mapped_fields;
    CREATE TEMP TABLE claim_mapped_fields ON COMMIT DROP AS
    SELECT DISTINCT ON (
        batch.observation_id, mapping.document_kind, mapping.source_field
    )
        batch.observation_id, batch.tenant_id, batch.source_instance_id,
        batch.entity_source_link_id, batch.entity_id,
        batch.classified_entity_class_id AS entity_class_id,
        batch.external_namespace, batch.parent_external_namespace,
        batch.parent_external_id, batch.external_id, batch.entity_type,
        batch.observed_at, batch.last_received_at, batch.active,
        batch.withdrawn_at, mapping.id AS source_mapping_id,
        mapping.document_kind, mapping.source_field, mapping.mapping_version,
        definition.id AS attribute_definition_id, definition.value_type,
        definition.cardinality, definition.sensitivity,
        CASE mapping.document_kind
          WHEN 'raw' THEN batch.raw_data -> mapping.source_field
          ELSE batch.canonical_data -> mapping.source_field
        END AS source_value
    FROM claim_projection_batch batch
    JOIN source_field_mappings mapping
      ON mapping.enabled
     AND (mapping.source_id IS NULL OR mapping.source_id = batch.source_id)
     AND (mapping.external_namespace = ''
          OR mapping.external_namespace = batch.external_namespace)
     AND (mapping.native_record_type = ''
          OR mapping.native_record_type = batch.entity_type)
    JOIN attribute_definitions definition
      ON definition.id = mapping.attribute_definition_id
     AND definition.enabled
     AND definition.entity_class_id = batch.classified_entity_class_id
    WHERE CASE mapping.document_kind
          WHEN 'raw' THEN batch.raw_data ? mapping.source_field
          ELSE batch.canonical_data ? mapping.source_field
          END
      AND CASE mapping.document_kind
          WHEN 'raw' THEN batch.raw_data -> mapping.source_field
          ELSE batch.canonical_data -> mapping.source_field
          END <> 'null'::jsonb
    ORDER BY batch.observation_id, mapping.document_kind, mapping.source_field,
             (mapping.source_id IS NOT NULL) DESC,
             (mapping.external_namespace <> '') DESC,
             (mapping.native_record_type <> '') DESC,
             mapping.mapping_version DESC, mapping.id DESC;

    DROP TABLE IF EXISTS pg_temp.desired_claims;
    CREATE TEMP TABLE desired_claims ON COMMIT DROP AS
    WITH expanded AS (
        SELECT mapped.*,
               member.value AS member_value,
               member.value #>> '{}' AS scalar_value
        FROM claim_mapped_fields mapped
        CROSS JOIN LATERAL jsonb_array_elements(
            CASE
              WHEN mapped.cardinality = 'set'
               AND jsonb_typeof(mapped.source_value) = 'array'
                THEN mapped.source_value
              ELSE jsonb_build_array(mapped.source_value)
            END
        ) AS member(value)
        WHERE mapped.active AND mapped.entity_id IS NOT NULL
    ), typed AS (
        SELECT expanded.*,
               CASE WHEN value_type = 'text'
                          AND jsonb_typeof(member_value) IN ('string','number','boolean')
                    THEN NULLIF(btrim(scalar_value), '') END AS value_text,
               CASE WHEN value_type = 'number'
                    THEN try_claim_numeric(scalar_value) END AS value_number,
               CASE WHEN value_type = 'boolean' THEN CASE lower(scalar_value)
                    WHEN 'true' THEN TRUE WHEN 't' THEN TRUE WHEN '1' THEN TRUE
                    WHEN 'yes' THEN TRUE WHEN 'false' THEN FALSE WHEN 'f' THEN FALSE
                    WHEN '0' THEN FALSE WHEN 'no' THEN FALSE END END AS value_boolean,
               CASE WHEN value_type = 'timestamp'
                    THEN try_claim_timestamptz(scalar_value) END AS value_timestamp,
               CASE WHEN value_type = 'entity_reference'
                    THEN try_claim_uuid(scalar_value) END AS value_entity_id,
               CASE WHEN value_type = 'structured'
                          AND jsonb_typeof(member_value) IN ('object','array')
                    THEN member_value END AS value_json
        FROM expanded
    ), valid AS (
        SELECT typed.*,
               pg_catalog.sha256(convert_to(
                   value_type || ':' || CASE value_type
                     WHEN 'text' THEN value_text
                     WHEN 'number' THEN value_number::text
                     WHEN 'boolean' THEN value_boolean::text
                     WHEN 'timestamp' THEN value_timestamp::text
                     WHEN 'entity_reference' THEN value_entity_id::text
                     WHEN 'structured' THEN value_json::text
                   END,
                   'UTF8'
               )) AS value_fingerprint
        FROM typed
        WHERE CASE value_type
          WHEN 'text' THEN value_text IS NOT NULL
          WHEN 'number' THEN value_number IS NOT NULL
          WHEN 'boolean' THEN value_boolean IS NOT NULL
          WHEN 'timestamp' THEN value_timestamp IS NOT NULL
          WHEN 'entity_reference' THEN value_entity_id IS NOT NULL AND EXISTS (
              SELECT 1 FROM entities referenced
              WHERE referenced.tenant_id = typed.tenant_id
                AND referenced.id = typed.value_entity_id
          )
          WHEN 'structured' THEN value_json IS NOT NULL
          ELSE FALSE END
    )
    SELECT DISTINCT ON (
        valid.observation_id, valid.attribute_definition_id,
        CASE WHEN valid.cardinality = 'single'
             THEN pg_catalog.sha256(convert_to('single', 'UTF8'))
             ELSE valid.value_fingerprint END
    )
        valid.*,
        CASE WHEN valid.cardinality = 'single'
             THEN pg_catalog.sha256(convert_to('single', 'UTF8'))
             ELSE valid.value_fingerprint END
            AS member_key,
        COALESCE(policy.eligible, FALSE) AND COALESCE(policy.enabled, FALSE)
            AS authority_eligible,
        CASE WHEN COALESCE(policy.enabled, FALSE)
             THEN policy.authority_tier ELSE 0 END AS authority_tier,
        CASE WHEN COALESCE(policy.enabled, FALSE)
             THEN policy.priority ELSE 0 END AS authority_priority,
        COALESCE(history.effective_from, valid.observed_at) AS effective_from
    FROM valid
    LEFT JOIN attribute_authority_policies policy
      ON policy.tenant_id = valid.tenant_id
     AND policy.source_instance_id = valid.source_instance_id
     AND policy.native_record_type = valid.entity_type
     AND policy.attribute_definition_id = valid.attribute_definition_id
    LEFT JOIN entity_observation_history history
     ON history.tenant_id = valid.tenant_id
     AND history.source_instance_id = valid.source_instance_id
     AND history.external_namespace = valid.external_namespace
     AND history.parent_external_namespace = valid.parent_external_namespace
     AND history.parent_external_id = valid.parent_external_id
     AND history.external_id = valid.external_id
     AND history.effective_to IS NULL
    ORDER BY valid.observation_id, valid.attribute_definition_id,
             CASE WHEN valid.cardinality = 'single'
                  THEN pg_catalog.sha256(convert_to('single', 'UTF8'))
                  ELSE valid.value_fingerprint END,
             valid.source_mapping_id DESC;

    DROP TABLE IF EXISTS pg_temp.claim_rows_to_change;
    CREATE TEMP TABLE claim_rows_to_change ON COMMIT DROP AS
    SELECT current.id,
           CASE WHEN desired.observation_id IS NULL
                THEN CASE WHEN batch.active THEN 'claim_withdrawn'
                          ELSE 'source_withdrawn' END
                ELSE 'claim_changed' END AS close_reason
    FROM entity_attribute_claim_current current
    JOIN claim_projection_batch batch
      ON batch.tenant_id = current.tenant_id
     AND batch.observation_id = current.observation_id
    LEFT JOIN desired_claims desired
      ON desired.tenant_id = current.tenant_id
     AND desired.observation_id = current.observation_id
     AND desired.attribute_definition_id = current.attribute_definition_id
     AND desired.member_key = current.member_key
    WHERE current.active
      AND (
          desired.observation_id IS NULL
          OR (current.entity_id, current.entity_class_id,
              current.source_instance_id, current.source_mapping_id,
              current.value_type, current.cardinality, current.value_text,
              current.value_number, current.value_boolean,
              current.value_timestamp, current.value_entity_id,
              current.value_json, current.value_fingerprint,
              current.mapping_version, current.authority_eligible,
              current.authority_tier, current.authority_priority)
             IS DISTINCT FROM
             (desired.entity_id, desired.entity_class_id,
              desired.source_instance_id, desired.source_mapping_id,
              desired.value_type, desired.cardinality, desired.value_text,
              desired.value_number, desired.value_boolean,
              desired.value_timestamp, desired.value_entity_id,
              desired.value_json, desired.value_fingerprint,
              desired.mapping_version, desired.authority_eligible,
              desired.authority_tier, desired.authority_priority)
      );

    UPDATE entity_attribute_claim_history history
       SET effective_to = projected_at,
           closed_reason = changed.close_reason
      FROM claim_rows_to_change changed
     WHERE history.current_claim_id = changed.id
       AND history.effective_to IS NULL;
    GET DIAGNOSTICS closed_history = ROW_COUNT;

    UPDATE entity_attribute_claim_current current
       SET entity_id = desired.entity_id,
           entity_class_id = desired.entity_class_id,
           source_instance_id = desired.source_instance_id,
           source_mapping_id = desired.source_mapping_id,
           value_type = desired.value_type,
           cardinality = desired.cardinality,
           value_text = desired.value_text,
           value_number = desired.value_number,
           value_boolean = desired.value_boolean,
           value_timestamp = desired.value_timestamp,
           value_entity_id = desired.value_entity_id,
           value_json = desired.value_json,
           value_fingerprint = desired.value_fingerprint,
           mapping_version = desired.mapping_version,
           authority_eligible = desired.authority_eligible,
           authority_tier = desired.authority_tier,
           authority_priority = desired.authority_priority,
           first_observed_at = desired.effective_from,
           last_observed_at = desired.observed_at,
           active = TRUE,
           withdrawn_at = NULL,
           version = current.version + 1
      FROM desired_claims desired
     WHERE current.tenant_id = desired.tenant_id
       AND current.observation_id = desired.observation_id
       AND current.attribute_definition_id = desired.attribute_definition_id
       AND current.member_key = desired.member_key
       AND (current.entity_id, current.entity_class_id,
            current.source_instance_id, current.source_mapping_id,
            current.value_type, current.cardinality, current.value_text,
            current.value_number, current.value_boolean,
            current.value_timestamp, current.value_entity_id,
            current.value_json, current.value_fingerprint,
            current.mapping_version, current.authority_eligible,
            current.authority_tier, current.authority_priority, current.active)
           IS DISTINCT FROM
           (desired.entity_id, desired.entity_class_id,
            desired.source_instance_id, desired.source_mapping_id,
            desired.value_type, desired.cardinality, desired.value_text,
            desired.value_number, desired.value_boolean,
            desired.value_timestamp, desired.value_entity_id,
            desired.value_json, desired.value_fingerprint,
            desired.mapping_version, desired.authority_eligible,
            desired.authority_tier, desired.authority_priority, TRUE);
    GET DIAGNOSTICS updated_claims = ROW_COUNT;

    INSERT INTO entity_attribute_claim_current (
        id, tenant_id, version, entity_id, entity_class_id, observation_id,
        source_instance_id, attribute_definition_id, source_mapping_id,
        value_type, cardinality, value_text, value_number, value_boolean,
        value_timestamp, value_entity_id, value_json, value_fingerprint,
        member_key, mapping_version, authority_eligible, authority_tier,
        authority_priority, first_observed_at, last_observed_at, active,
        withdrawn_at
    )
    SELECT gen_random_uuid(), desired.tenant_id, 1, desired.entity_id,
           desired.entity_class_id, desired.observation_id,
           desired.source_instance_id, desired.attribute_definition_id,
           desired.source_mapping_id, desired.value_type, desired.cardinality,
           desired.value_text, desired.value_number, desired.value_boolean,
           desired.value_timestamp, desired.value_entity_id, desired.value_json,
           desired.value_fingerprint, desired.member_key,
           desired.mapping_version, desired.authority_eligible,
           desired.authority_tier, desired.authority_priority,
           desired.effective_from, desired.observed_at, TRUE, NULL
    FROM desired_claims desired
    LEFT JOIN entity_attribute_claim_current current
      ON current.tenant_id = desired.tenant_id
     AND current.observation_id = desired.observation_id
     AND current.attribute_definition_id = desired.attribute_definition_id
     AND current.member_key = desired.member_key
    WHERE current.id IS NULL;
    GET DIAGNOSTICS inserted_claims = ROW_COUNT;

    UPDATE entity_attribute_claim_current current
       SET active = FALSE,
           withdrawn_at = COALESCE(batch.withdrawn_at, batch.observed_at,
                                   projected_at),
           version = current.version + 1
      FROM claim_projection_batch batch
     WHERE current.tenant_id = batch.tenant_id
       AND current.observation_id = batch.observation_id
       AND current.active
       AND NOT EXISTS (
           SELECT 1 FROM desired_claims desired
           WHERE desired.tenant_id = current.tenant_id
             AND desired.observation_id = current.observation_id
             AND desired.attribute_definition_id = current.attribute_definition_id
             AND desired.member_key = current.member_key
       );
    GET DIAGNOSTICS withdrawn_claims = ROW_COUNT;

    INSERT INTO entity_attribute_claim_history (
        id, tenant_id, current_claim_id, entity_id, entity_class_id,
        observation_id, source_instance_id, attribute_definition_id,
        source_mapping_id, value_type, cardinality, value_text, value_number,
        value_boolean, value_timestamp, value_entity_id, value_json,
        value_fingerprint, member_key, mapping_version, authority_eligible,
        authority_tier, authority_priority, effective_from, effective_to,
        closed_reason
    )
    SELECT gen_random_uuid(), current.tenant_id, current.id, current.entity_id,
           current.entity_class_id, current.observation_id,
           current.source_instance_id, current.attribute_definition_id,
           current.source_mapping_id, current.value_type, current.cardinality,
           current.value_text, current.value_number, current.value_boolean,
           current.value_timestamp, current.value_entity_id,
           current.value_json, current.value_fingerprint, current.member_key,
           current.mapping_version, current.authority_eligible,
           current.authority_tier, current.authority_priority,
           CASE WHEN EXISTS (
               SELECT 1
               FROM entity_attribute_claim_history prior
               WHERE prior.tenant_id = current.tenant_id
                 AND prior.current_claim_id = current.id
           ) THEN GREATEST(
               desired.effective_from,
               COALESCE((
                   SELECT MAX(prior.effective_to)
                   FROM entity_attribute_claim_history prior
                   WHERE prior.tenant_id = current.tenant_id
                     AND prior.current_claim_id = current.id
               ), projected_at)
           ) ELSE desired.effective_from END,
           NULL, ''
    FROM entity_attribute_claim_current current
    JOIN desired_claims desired
      ON desired.tenant_id = current.tenant_id
     AND desired.observation_id = current.observation_id
     AND desired.attribute_definition_id = current.attribute_definition_id
     AND desired.member_key = current.member_key
    LEFT JOIN entity_attribute_claim_history history
      ON history.tenant_id = current.tenant_id
     AND history.current_claim_id = current.id
     AND history.effective_to IS NULL
    WHERE current.active AND history.id IS NULL;
    GET DIAGNOSTICS inserted_history = ROW_COUNT;

    WITH field_inventory AS (
        SELECT batch.observation_id, batch.tenant_id, batch.source_instance_id,
               batch.active, 'canonical'::text AS document_kind, field.key
        FROM claim_projection_batch batch
        CROSS JOIN LATERAL jsonb_each(COALESCE(batch.canonical_data, '{}'::jsonb)) field
        WHERE field.value <> 'null'::jsonb
        UNION ALL
        SELECT batch.observation_id, batch.tenant_id, batch.source_instance_id,
               batch.active, 'raw'::text, field.key
        FROM claim_projection_batch batch
        CROSS JOIN LATERAL jsonb_each(COALESCE(batch.raw_data, '{}'::jsonb)) field
        WHERE field.value <> 'null'::jsonb
    ), counts AS (
        SELECT batch.observation_id, batch.tenant_id, batch.source_instance_id,
               batch.active,
               COUNT(inventory.key)::integer AS observed_field_count,
               COUNT(mapped.source_field)::integer AS mapped_field_count,
               COUNT(inventory.key) FILTER (
                   WHERE mapped.source_field IS NULL
               )::integer AS unmapped_field_count,
               COUNT(inventory.key) FILTER (
                   WHERE mapped.source_field IS NULL
                      OR mapped.sensitivity = 'restricted'
               )::integer AS restricted_field_count,
               COUNT(mapped.source_field) FILTER (
                   WHERE mapped.active
                     AND (
                         mapped.cardinality <> 'set'
                         OR jsonb_typeof(mapped.source_value) <> 'array'
                         OR jsonb_array_length(mapped.source_value) > 0
                     )
                     AND NOT EXISTS (
                         SELECT 1 FROM desired_claims desired
                         WHERE desired.observation_id = mapped.observation_id
                           AND desired.source_mapping_id = mapped.source_mapping_id
                     )
               )::integer AS invalid_field_count,
               (SELECT COUNT(*)::integer FROM desired_claims desired
                 WHERE desired.observation_id = batch.observation_id)
                   AS projected_claim_count
        FROM claim_projection_batch batch
        LEFT JOIN field_inventory inventory
          ON inventory.observation_id = batch.observation_id
        LEFT JOIN claim_mapped_fields mapped
          ON mapped.observation_id = inventory.observation_id
         AND mapped.document_kind = inventory.document_kind
         AND mapped.source_field = inventory.key
        GROUP BY batch.observation_id, batch.tenant_id,
                 batch.source_instance_id, batch.active
    )
    INSERT INTO entity_attribute_withheld_current (
        id, tenant_id, observation_id, source_instance_id,
        observed_field_count, mapped_field_count, unmapped_field_count,
        restricted_field_count, invalid_field_count, projected_claim_count,
        active, projection_contract_version, measured_at
    )
    SELECT gen_random_uuid(), counts.tenant_id, counts.observation_id,
           counts.source_instance_id, counts.observed_field_count,
           counts.mapped_field_count, counts.unmapped_field_count,
           counts.restricted_field_count, counts.invalid_field_count,
           counts.projected_claim_count, counts.active,
           projection_contract, projected_at
    FROM counts
    ON CONFLICT (observation_id) DO UPDATE SET
        tenant_id = EXCLUDED.tenant_id,
        source_instance_id = EXCLUDED.source_instance_id,
        observed_field_count = EXCLUDED.observed_field_count,
        mapped_field_count = EXCLUDED.mapped_field_count,
        unmapped_field_count = EXCLUDED.unmapped_field_count,
        restricted_field_count = EXCLUDED.restricted_field_count,
        invalid_field_count = EXCLUDED.invalid_field_count,
        projected_claim_count = EXCLUDED.projected_claim_count,
        active = EXCLUDED.active,
        projection_contract_version = EXCLUDED.projection_contract_version,
        measured_at = EXCLUDED.measured_at
    WHERE (entity_attribute_withheld_current.tenant_id,
           entity_attribute_withheld_current.source_instance_id,
           entity_attribute_withheld_current.observed_field_count,
           entity_attribute_withheld_current.mapped_field_count,
           entity_attribute_withheld_current.unmapped_field_count,
           entity_attribute_withheld_current.restricted_field_count,
           entity_attribute_withheld_current.invalid_field_count,
           entity_attribute_withheld_current.projected_claim_count,
           entity_attribute_withheld_current.active,
           entity_attribute_withheld_current.projection_contract_version)
          IS DISTINCT FROM
          (EXCLUDED.tenant_id, EXCLUDED.source_instance_id,
           EXCLUDED.observed_field_count, EXCLUDED.mapped_field_count,
           EXCLUDED.unmapped_field_count, EXCLUDED.restricted_field_count,
           EXCLUDED.invalid_field_count, EXCLUDED.projected_claim_count,
           EXCLUDED.active, EXCLUDED.projection_contract_version);
    GET DIAGNOSTICS withheld_writes = ROW_COUNT;

    INSERT INTO entity_attribute_projection_state (
        observation_id, tenant_id, source_instance_id, entity_source_link_id,
        entity_id, projection_hash, observation_active,
        projection_contract_version, projected_at
    )
    SELECT observation_id, tenant_id, source_instance_id,
           entity_source_link_id, entity_id, projection_hash, active,
           projection_contract, projected_at
    FROM claim_projection_batch
    ON CONFLICT (observation_id) DO UPDATE SET
        tenant_id = EXCLUDED.tenant_id,
        source_instance_id = EXCLUDED.source_instance_id,
        entity_source_link_id = EXCLUDED.entity_source_link_id,
        entity_id = EXCLUDED.entity_id,
        projection_hash = EXCLUDED.projection_hash,
        observation_active = EXCLUDED.observation_active,
        projection_contract_version = EXCLUDED.projection_contract_version,
        projected_at = EXCLUDED.projected_at;

    RETURN jsonb_build_object(
        'status', 'projected', 'processed', batch_rows,
        'inserted_claims', inserted_claims,
        'updated_claims', updated_claims,
        'withdrawn_claims', withdrawn_claims,
        'inserted_history', inserted_history,
        'closed_history', closed_history,
        'withheld_writes', withheld_writes
    );
END;
$function$;

CREATE OR REPLACE FUNCTION operations.purge_closed_attribute_claim_history(
    cutoff timestamptz,
    batch_size integer DEFAULT 10000
)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = operations, pg_temp
AS $function$
DECLARE
    deleted_rows bigint;
BEGIN
    IF batch_size < 1 OR batch_size > 100000 THEN
        RAISE EXCEPTION 'batch_size must be between 1 and 100000';
    END IF;
    WITH expired AS (
        SELECT id
        FROM entity_attribute_claim_history
        WHERE effective_to IS NOT NULL AND effective_to < cutoff
        ORDER BY effective_to, id
        LIMIT batch_size
        FOR UPDATE SKIP LOCKED
    )
    DELETE FROM entity_attribute_claim_history history
    USING expired
    WHERE history.id = expired.id;
    GET DIAGNOSTICS deleted_rows = ROW_COUNT;
    RETURN deleted_rows;
END;
$function$;

CREATE OR REPLACE VIEW operations.v_entity_attribute_claim_current
WITH (security_barrier = true) AS
SELECT claim.id, claim.tenant_id, claim.entity_id,
       claim.entity_class_id AS entity_class, claim.observation_id,
       claim.source_instance_id, definition.key AS attribute_key,
       definition.display_name AS attribute_display_name,
       definition.sensitivity, claim.cardinality,
       CASE
         WHEN definition.sensitivity IN ('sensitive', 'restricted')
           THEN '[redacted]'
         WHEN claim.value_type = 'text' THEN claim.value_text
         WHEN claim.value_type = 'number' THEN claim.value_number::text
         WHEN claim.value_type = 'boolean' THEN claim.value_boolean::text
         WHEN claim.value_type = 'timestamp' THEN claim.value_timestamp::text
         WHEN claim.value_type = 'entity_reference' THEN claim.value_entity_id::text
         WHEN claim.value_type = 'structured' THEN '[structured]'
         ELSE '[unknown]'
       END AS value_display,
       claim.authority_eligible, claim.authority_tier,
       claim.authority_priority, claim.first_observed_at,
       claim.last_observed_at
FROM operations.entity_attribute_claim_current claim
JOIN operations.attribute_definitions definition
  ON definition.id = claim.attribute_definition_id
WHERE claim.active
  AND claim.tenant_id = operations.current_tenant_id();

CREATE OR REPLACE VIEW operations.v_entity_attribute_claim_storage_status
WITH (security_barrier = true) AS
SELECT tenant.id AS tenant_id,
       (SELECT COUNT(*) FROM operations.entity_attribute_claim_current current
         WHERE current.tenant_id = tenant.id) AS current_claim_rows,
       (SELECT COUNT(*) FROM operations.entity_attribute_claim_current current
         WHERE current.tenant_id = tenant.id AND current.active) AS active_claim_rows,
       (SELECT COUNT(*) FROM operations.entity_attribute_claim_history history
         WHERE history.tenant_id = tenant.id) AS history_claim_rows,
       (SELECT COUNT(*) FROM operations.entity_attribute_claim_history history
         WHERE history.tenant_id = tenant.id
           AND history.effective_to >= NOW() - INTERVAL '1 day')
           AS changed_members_1d,
       ((SELECT COUNT(*) FROM operations.entity_attribute_claim_history history
          WHERE history.tenant_id = tenant.id) >= 10000000
        OR
        (SELECT COUNT(*) FROM operations.entity_attribute_claim_history history
          WHERE history.tenant_id = tenant.id
            AND history.effective_to >= NOW() - INTERVAL '1 day') >= 25000)
           AS partition_review_required
FROM operations.tenants tenant
WHERE tenant.id = operations.current_tenant_id();

REVOKE ALL ON FUNCTION operations.current_tenant_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.try_claim_numeric(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.try_claim_timestamptz(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.try_claim_uuid(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.sync_entity_attribute_claims_from_observations(integer)
    FROM PUBLIC;
REVOKE ALL ON FUNCTION operations.purge_closed_attribute_claim_history(timestamptz, integer)
    FROM PUBLIC;

GRANT EXECUTE ON FUNCTION operations.current_tenant_id()
    TO operations_app, ninja_ingest, operations_readonly;
GRANT EXECUTE ON FUNCTION operations.sync_entity_attribute_claims_from_observations(integer)
    TO ninja_ingest;
GRANT EXECUTE ON FUNCTION operations.purge_closed_attribute_claim_history(timestamptz, integer)
    TO ninja_ingest;

REVOKE ALL ON operations.entity_attribute_claim_current,
    operations.entity_attribute_claim_history FROM operations_app,
    operations_readonly, metabase_ro;
GRANT SELECT ON operations.attribute_definitions,
    operations.source_field_mappings, operations.identity_authority_policies,
    operations.attribute_authority_policies,
    operations.entity_attribute_withheld_current,
    operations.entity_attribute_projection_state,
    operations.v_entity_attribute_claim_current,
    operations.v_entity_attribute_claim_storage_status
    TO operations_app, operations_readonly;
GRANT SELECT ON operations.attribute_definitions,
    operations.source_field_mappings, operations.identity_authority_policies,
    operations.attribute_authority_policies,
    operations.entity_attribute_withheld_current,
    operations.entity_attribute_projection_state,
    operations.v_entity_attribute_claim_storage_status
    TO ninja_ingest;

ALTER FUNCTION operations.current_tenant_id() OWNER TO operations_migrate;
ALTER FUNCTION operations.try_claim_numeric(text) OWNER TO operations_migrate;
ALTER FUNCTION operations.try_claim_timestamptz(text) OWNER TO operations_migrate;
ALTER FUNCTION operations.try_claim_uuid(text) OWNER TO operations_migrate;
ALTER FUNCTION operations.sync_entity_attribute_claims_from_observations(integer)
    OWNER TO operations_migrate;
ALTER FUNCTION operations.purge_closed_attribute_claim_history(timestamptz, integer)
    OWNER TO operations_migrate;
ALTER VIEW operations.v_entity_attribute_claim_current OWNER TO operations_migrate;
ALTER VIEW operations.v_entity_attribute_claim_storage_status OWNER TO operations_migrate;
ALTER TABLE operations.attribute_definitions OWNER TO operations_migrate;
ALTER TABLE operations.source_field_mappings OWNER TO operations_migrate;
ALTER TABLE operations.identity_authority_policies OWNER TO operations_migrate;
ALTER TABLE operations.attribute_authority_policies OWNER TO operations_migrate;
ALTER TABLE operations.entity_attribute_claim_current OWNER TO operations_migrate;
ALTER TABLE operations.entity_attribute_claim_history OWNER TO operations_migrate;
ALTER TABLE operations.entity_attribute_withheld_current OWNER TO operations_migrate;
ALTER TABLE operations.entity_attribute_projection_state OWNER TO operations_migrate;
"""


REVERSE_SQL = r"""
DROP VIEW IF EXISTS operations.v_entity_attribute_claim_storage_status;
DROP VIEW IF EXISTS operations.v_entity_attribute_claim_current;
DROP FUNCTION IF EXISTS operations.purge_closed_attribute_claim_history(timestamptz, integer);
DROP FUNCTION IF EXISTS operations.sync_entity_attribute_claims_from_observations(integer);
DROP FUNCTION IF EXISTS operations.try_claim_uuid(text);
DROP FUNCTION IF EXISTS operations.try_claim_timestamptz(text);
DROP FUNCTION IF EXISTS operations.try_claim_numeric(text);
DROP FUNCTION IF EXISTS operations.current_tenant_id();
ALTER TABLE operations.entity_attribute_projection_state
    DROP CONSTRAINT IF EXISTS fk_attr_state_tenant_observation,
    DROP CONSTRAINT IF EXISTS fk_attr_state_tenant_source,
    DROP CONSTRAINT IF EXISTS fk_attr_state_tenant_link,
    DROP CONSTRAINT IF EXISTS fk_attr_state_tenant_entity;
ALTER TABLE operations.entity_attribute_withheld_current
    DROP CONSTRAINT IF EXISTS fk_attr_withheld_tenant_observation,
    DROP CONSTRAINT IF EXISTS fk_attr_withheld_tenant_source;
ALTER TABLE operations.entity_attribute_claim_history
    DROP CONSTRAINT IF EXISTS fk_attr_hist_tenant_current,
    DROP CONSTRAINT IF EXISTS fk_attr_hist_tenant_entity_class,
    DROP CONSTRAINT IF EXISTS fk_attr_hist_tenant_observation,
    DROP CONSTRAINT IF EXISTS fk_attr_hist_tenant_source,
    DROP CONSTRAINT IF EXISTS fk_attr_hist_tenant_value_entity,
    DROP CONSTRAINT IF EXISTS fk_attr_hist_definition_type;
ALTER TABLE operations.entity_attribute_claim_current
    DROP CONSTRAINT IF EXISTS fk_attr_claim_tenant_entity_class,
    DROP CONSTRAINT IF EXISTS fk_attr_claim_tenant_observation,
    DROP CONSTRAINT IF EXISTS fk_attr_claim_tenant_source,
    DROP CONSTRAINT IF EXISTS fk_attr_claim_tenant_value_entity,
    DROP CONSTRAINT IF EXISTS fk_attr_claim_definition_type;
ALTER TABLE operations.attribute_authority_policies
    DROP CONSTRAINT IF EXISTS fk_attr_policy_tenant_source;
ALTER TABLE operations.identity_authority_policies
    DROP CONSTRAINT IF EXISTS fk_identity_policy_tenant_source;
ALTER TABLE operations.entity_source_links
    DROP CONSTRAINT IF EXISTS uq_entity_source_links_tenant_id;
ALTER TABLE operations.entity_observation_current
    DROP CONSTRAINT IF EXISTS uq_obs_current_tenant_observation;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("operations", "0102_generic_attribute_delta_claims"),
    ]

    operations = [
        migrations.RunSQL(SCHEMA_INDEX_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(ATTRIBUTE_CONTRACT_SQL, migrations.RunSQL.noop),
        migrations.RunSQL(PROJECTOR_SQL, REVERSE_SQL),
    ]
