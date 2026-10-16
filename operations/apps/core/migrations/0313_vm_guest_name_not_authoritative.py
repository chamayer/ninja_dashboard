"""A VM's name in the hypervisor does not name the Computer (ADR-0032).

Ninja ``vm.guest`` records carry the name the VM has in the hypervisor
inventory, which is often not the machine's own name (42 of 251 name
differences measured 2026-10-16 were won by a vm.guest claim). The hostname
authority policy for vm.guest becomes ineligible; the record still matches
and is still shown, it just no longer selects the Computer's stored name.

Claims carry the policy at projection time, so the projection state of the
vm.guest observations is invalidated (a cache, exempt from history): the
claim projector re-derives their claims under the new policy on its next
runs, through its normal path.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
SELECT operations.begin_change(
    'attribute_authority.vm_guest_hostname',
    'ADR-0032: a VM''s name in the hypervisor does not name the Computer.',
    '{"migration": "0313_vm_guest_name_not_authoritative"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0313', NULL, true);

UPDATE operations.attribute_authority_policies policy
   SET eligible = FALSE,
       reason = 'ADR-0032: a VM''s name in the hypervisor does not name the Computer.',
       version = policy.version + 1
  FROM operations.attribute_definitions definition
 WHERE definition.id = policy.attribute_definition_id
   AND definition.key = 'hostname'
   AND policy.native_record_type = 'vm.guest'
   AND policy.eligible;

DELETE FROM operations.entity_attribute_projection_state state
 USING operations.entity_observation_current observation
 WHERE observation.observation_id = state.observation_id
   AND observation.tenant_id = state.tenant_id
   AND observation.entity_type = 'vm.guest';
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0312_hudu_documentation_required"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop),
    ]
