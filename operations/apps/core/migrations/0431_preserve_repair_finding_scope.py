"""Keep historical finding and software scopes through repair ownership changes."""

from importlib import import_module
from typing import ClassVar

from django.db import migrations

_projector = import_module("apps.core.migrations.0402_computer_client_projector").FORWARD_SQL
_start = _projector.index("CREATE FUNCTION operations.project_computer_client(")
_end = _projector.index("\nREVOKE ALL ON FUNCTION operations.project_computer_client", _start)
REVERSE_SQL = _projector[_start:_end].replace("CREATE FUNCTION ", "CREATE OR REPLACE FUNCTION ", 1)


def _replace_once(sql: str, old: str, new: str) -> str:
    if sql.count(old) != 1:
        raise RuntimeError("Unexpected Computer client projector definition")
    return sql.replace(old, new)


FORWARD_SQL = _replace_once(
    REVERSE_SQL,
    "    v_needs_update boolean;",
    "    v_needs_update boolean;\n    v_preserve_finding_client boolean;",
)
FORWARD_SQL = _replace_once(
    FORWARD_SQL,
    """    IF v_client IS NOT NULL THEN
        SELECT coalesce(array_agg(DISTINCT relationship.source_entity_id), '{}'::uuid[])""",
    """    IF v_client IS NOT NULL THEN
        SELECT EXISTS (
            SELECT 1 FROM operations.computer_merges repaired
            JOIN operations.change_actions action
              ON action.tenant_id = repaired.tenant_id AND action.id = repaired.action_id
             AND action.action = 'computer.merge.cross_client'
            WHERE repaired.tenant_id = p_tenant
              AND p_device IN (repaired.survivor_id, repaired.absorbed_id)
        ) INTO v_preserve_finding_client;
        SELECT coalesce(array_agg(DISTINCT relationship.source_entity_id), '{}'::uuid[])""",
)
FORWARD_SQL = _replace_once(
    FORWARD_SQL,
    """                OR EXISTS (SELECT 1 FROM operations.findings WHERE tenant_id = p_tenant
                            AND subject_type = 'device' AND subject_id = d.id
                            AND client_id IS DISTINCT FROM v_client)""",
    """                OR (NOT v_preserve_finding_client AND EXISTS (
                            SELECT 1 FROM operations.findings WHERE tenant_id = p_tenant
                            AND subject_type = 'device' AND subject_id = d.id
                            AND client_id IS DISTINCT FROM v_client))""",
)
FORWARD_SQL = _replace_once(
    FORWARD_SQL,
    """            UPDATE operations.findings SET client_id = v_client
             WHERE tenant_id = p_tenant AND subject_type = 'device' AND subject_id = d.id
               AND client_id IS DISTINCT FROM v_client;""",
    """            IF NOT v_preserve_finding_client THEN
                UPDATE operations.findings SET client_id = v_client
                 WHERE tenant_id = p_tenant AND subject_type = 'device' AND subject_id = d.id
                   AND client_id IS DISTINCT FROM v_client;
            END IF;""",
)
FORWARD_SQL = _replace_once(
    FORWARD_SQL,
    """                OR EXISTS (SELECT 1 FROM operations.software_installations_current
                            WHERE tenant_id = p_tenant AND device_id = d.id
                              AND client_id IS DISTINCT FROM v_client)
                OR EXISTS (SELECT 1 FROM operations.software_decisions
                            WHERE tenant_id = p_tenant AND device_id = d.id
                              AND client_id = d.client_id AND client_id IS DISTINCT FROM v_client)""",
    """                OR (NOT v_preserve_finding_client AND EXISTS (
                    SELECT 1 FROM operations.software_installations_current
                     WHERE tenant_id = p_tenant AND device_id = d.id AND client_id IS DISTINCT FROM v_client))
                OR (NOT v_preserve_finding_client AND EXISTS (
                    SELECT 1 FROM operations.software_decisions
                     WHERE tenant_id = p_tenant AND device_id = d.id
                       AND client_id = d.client_id AND client_id IS DISTINCT FROM v_client))""",
)
FORWARD_SQL = _replace_once(
    FORWARD_SQL,
    """            UPDATE operations.software_installations_current SET client_id = v_client
             WHERE tenant_id = p_tenant AND device_id = d.id AND client_id IS DISTINCT FROM v_client;
            -- Preserve decisions whose client was intentionally broad or has
            -- another explicit scope; do not convert a NULL to a client.
            UPDATE operations.software_decisions SET client_id = v_client
             WHERE tenant_id = p_tenant AND device_id = d.id AND client_id = d.client_id
               AND client_id IS DISTINCT FROM v_client;""",
    """            IF NOT v_preserve_finding_client THEN
                UPDATE operations.software_installations_current SET client_id = v_client
                 WHERE tenant_id = p_tenant AND device_id = d.id AND client_id IS DISTINCT FROM v_client;
                -- Preserve decisions with an explicit or intentionally broad scope.
                UPDATE operations.software_decisions SET client_id = v_client
                 WHERE tenant_id = p_tenant AND device_id = d.id AND client_id = d.client_id
                   AND client_id IS DISTINCT FROM v_client;
            END IF;""",
)


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0430_cross_client_repair_transaction"),
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
