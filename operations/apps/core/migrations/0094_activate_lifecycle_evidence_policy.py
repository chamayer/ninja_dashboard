"""Activate the reviewed Track A lifecycle-evidence policy.

Migration 0093 landed the policy schema inert so deployment compatibility and
production reconciliation could be validated separately. This migration is
the approved activation boundary. It refuses to proceed if a reviewed entity
type is missing or if any policy row is no longer inert, preventing an
unexpected registry state from being silently overwritten.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
DO $track_a$
DECLARE
    missing_types text;
    active_types text;
BEGIN
    SELECT string_agg(expected.name, ', ' ORDER BY expected.name)
      INTO missing_types
      FROM (VALUES
        ('agent.rmm'),
        ('agent.edr'),
        ('agent.remote_access'),
        ('vm.host'),
        ('vm.guest'),
        ('network.device'),
        ('monitor.target')
      ) AS expected(name)
      LEFT JOIN operations.entity_types et ON et.name = expected.name
     WHERE et.name IS NULL;

    IF missing_types IS NOT NULL THEN
        RAISE EXCEPTION
            'Track A lifecycle activation is missing reviewed entity types: %',
            missing_types;
    END IF;

    SELECT string_agg(name, ', ' ORDER BY name)
      INTO active_types
      FROM operations.entity_types
     WHERE lifecycle_evidence_mode <> 'none';

    IF active_types IS NOT NULL THEN
        RAISE EXCEPTION
            'Track A lifecycle activation expected an inert registry; active types: %',
            active_types;
    END IF;
END
$track_a$;

UPDATE operations.entity_types
   SET lifecycle_evidence_mode = CASE name
       WHEN 'agent.rmm' THEN 'direct_contact'
       WHEN 'agent.edr' THEN 'direct_contact'
       WHEN 'agent.remote_access' THEN 'direct_contact'
       WHEN 'vm.host' THEN 'direct_then_reported_state'
       WHEN 'vm.guest' THEN 'reported_state'
       WHEN 'network.device' THEN 'reported_state'
       WHEN 'monitor.target' THEN 'reported_state'
       ELSE lifecycle_evidence_mode
   END
 WHERE name IN (
    'agent.rmm',
    'agent.edr',
    'agent.remote_access',
    'vm.host',
    'vm.guest',
    'network.device',
    'monitor.target'
 );
"""

REVERSE_SQL = """
UPDATE operations.entity_types
   SET lifecycle_evidence_mode = 'none'
 WHERE name IN (
    'agent.rmm',
    'agent.edr',
    'agent.remote_access',
    'vm.host',
    'vm.guest',
    'network.device',
    'monitor.target'
 );
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0093_lifecycle_evidence_policy_and_audit"),
    ]

    operations: ClassVar[list] = [
        migrations.RunSQL(FORWARD_SQL, REVERSE_SQL),
    ]
