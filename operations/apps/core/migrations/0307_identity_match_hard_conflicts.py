"""Identity matching policy data for ADR-0032: hard conflicts, not same-source blocks.

Until now a name match was blocked by any other record of the same source on
the candidate (``avoid_same_stream_duplicates``) and required exactly one
candidate. Measured 2026-10-15/16, that split one machine across several
Computers (36 Computers in 13 same-name groups, 26 holding a serial stored on
another Computer) while name matching itself produced no proven wrong match.

The matcher now excludes a candidate only on a hard conflict, named per policy
in ``blocking_signal_keys``:

* ``serial``: the candidate's active records report a different usable serial
  (its last-known serial when it has none active);
* ``vm_uuid``: they report a different VM UUID;
* ``same_source_live``: a record of the same source and type is online on the
  candidate at the same time as the incoming one (two live installs; for VM
  records, two VM objects).

With several candidates the most recently active one is chosen, so
``requires_unique_candidate`` is off for every matcher except
``source_identity``. The serial matcher is blocked only by a VM UUID conflict
and the VM UUID matcher only by a serial conflict: two agents of one source on
one serial are duplicate agents on one machine, not two machines.

The change is recorded as one explicit action in the change history (ADR-0033).
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE operations.identity_match_policies
    DROP CONSTRAINT IF EXISTS ck_identity_match_policy_blockers;
ALTER TABLE operations.identity_match_policies
    ADD CONSTRAINT ck_identity_match_policy_blockers CHECK (
        jsonb_typeof(blocking_signal_keys) = 'array'
        AND blocking_signal_keys <@ '["serial", "vm_uuid", "same_source_live"]'::jsonb
    );

SELECT operations.begin_change(
    'identity_policy.hard_conflicts',
    'ADR-0032: name matching is blocked only by a hard conflict; the most recently active '
    || 'candidate is chosen when several match.',
    '{"migration": "0307_identity_match_hard_conflicts"}'::jsonb,
    'migration', NULL, 'operations.migrations', '0307', NULL, true)
 WHERE to_regprocedure(
     'operations.begin_change(text, text, jsonb, text, bigint, text, text, bigint, boolean)')
     IS NOT NULL;

UPDATE operations.identity_match_policies
   SET requires_unique_candidate = (matcher = 'source_identity'),
       avoid_same_stream_duplicates = FALSE,
       blocking_signal_keys = CASE matcher
           WHEN 'source_identity' THEN '[]'::jsonb
           WHEN 'serial' THEN '["vm_uuid"]'::jsonb
           WHEN 'vm_uuid' THEN '["serial"]'::jsonb
           ELSE '["serial", "vm_uuid", "same_source_live"]'::jsonb
       END,
       description = CASE matcher
           WHEN 'serial' THEN
               'Attach when a Computer in the client has an active record reporting the same '
               || 'usable serial number; a different VM UUID blocks it.'
           WHEN 'vm_uuid' THEN
               'Attach when a Computer in the client has an active record reporting the same '
               || 'VM UUID; a different serial number blocks it.'
           WHEN 'hostname_mac' THEN
               'Attach to a same-client Computer with the same name and a shared MAC address '
               || '(Hyper-V virtual adapters ignored), unless a hard conflict separates them.'
           WHEN 'hostname' THEN
               'Attach to a same-client Computer with the same name (also a 15-character cut or '
               || 'separator variant), unless a hard conflict separates them.'
           ELSE description
       END,
       reason = 'ADR-0032 (2026-10-16): hard conflicts only; most recently active candidate.',
       version = version + 1;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0306_change_history_foundation"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
