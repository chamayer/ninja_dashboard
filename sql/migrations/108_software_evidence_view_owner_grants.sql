-- 108: grant the dedicated read-model owner its explicit software-view inputs.
--
-- The source-aware software views in 107 deliberately run as the dedicated
-- non-login `operations_view_owner`.  A security-barrier view uses its
-- owner's table privileges, so application callers must not be granted these
-- underlying relations directly.  Migration 107 changed the view owners but
-- omitted the corresponding read dependencies, causing Computer Overview to
-- fail while resolving inherited software findings.

GRANT USAGE ON SCHEMA catalog TO operations_view_owner;

GRANT SELECT ON TABLE
    operations.findings,
    operations.finding_types,
    operations.source_bindings,
    operations.software_installations_current,
    operations.software_installation_history,
    operations.software_decisions,
    operations.evaluator_config,
    operations.device_agent_presence_current
TO operations_view_owner;

GRANT SELECT ON TABLE
    catalog.products,
    catalog.software_versions
TO operations_view_owner;

-- `operations_app` intentionally remains limited to the two public views:
-- `v_software_installation_evidence_current` and
-- `v_device_software_exposure`.
