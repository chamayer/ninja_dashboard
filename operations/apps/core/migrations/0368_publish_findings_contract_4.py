"""Verify the common findings ledger and publish contract 4 (PLAN-003 M4, final).

Last step of the coordinated M2-M4 artifact. Every check below must hold or the
whole artifact rolls back; only then does the database accept contract-4
writers. Processes built for another contract fail at their first findings write.

* The admin view returns exactly the retained legacy rows.
* Every finding has a state row; every assessment and participant belongs to a
  finding of its own namespace and tenant.
* No active condition key is duplicated within a namespace.
* Cover rules match ``finding_types.covered_by`` one to one.
"""

from __future__ import annotations

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = r"""
DO $$
DECLARE
    v bigint;
BEGIN
    SELECT count(*) INTO v FROM (
        (SELECT version, id, condition_key, severity, status, subject_ref, details,
                first_detected_at, last_detected_at, resolved_at, finding_type_id, tenant_id
           FROM operations.admin_findings_legacy
         EXCEPT
         SELECT * FROM operations.admin_findings)
        UNION ALL
        (SELECT * FROM operations.admin_findings
         EXCEPT
         SELECT version, id, condition_key, severity, status, subject_ref, details,
                first_detected_at, last_detected_at, resolved_at, finding_type_id, tenant_id
           FROM operations.admin_findings_legacy)) d;
    IF v > 0 THEN
        RAISE EXCEPTION 'M4: % admin rows differ between the view and the legacy ledger', v;
    END IF;

    SELECT count(*) INTO v FROM operations.findings f
     WHERE NOT EXISTS (SELECT 1 FROM operations.finding_state s WHERE s.finding_id = f.id);
    IF v > 0 THEN
        RAISE EXCEPTION 'M4: % findings have no state row', v;
    END IF;

    SELECT count(*) INTO v FROM (
        SELECT a.finding_id FROM operations.condition_assessments a
          JOIN operations.findings f ON f.id = a.finding_id
         WHERE a.row_kind <> f.condition_namespace OR a.tenant_id <> f.tenant_id
        UNION ALL
        SELECT p.finding_id FROM operations.condition_participants p
          JOIN operations.findings f ON f.id = p.finding_id
         WHERE p.row_kind <> f.condition_namespace OR p.tenant_id <> f.tenant_id) d;
    IF v > 0 THEN
        RAISE EXCEPTION 'M4: % assessment/participant rows disagree with their finding', v;
    END IF;

    SELECT count(*) INTO v FROM (
        SELECT tenant_id, condition_namespace, condition_key FROM operations.findings
         WHERE condition_key > ''
           AND status IN ('open', 'acknowledged', 'investigating', 'suppressed')
         GROUP BY 1, 2, 3 HAVING count(*) > 1) d;
    IF v > 0 THEN
        RAISE EXCEPTION 'M4: % active condition keys are duplicated in a namespace', v;
    END IF;

    SELECT count(*) INTO v FROM (
        (SELECT c.id, p.id FROM operations.finding_types c
          CROSS JOIN LATERAL jsonb_array_elements_text(c.covered_by) e(name)
          JOIN operations.finding_types p ON p.name = e.name
         EXCEPT
         SELECT child_type_id, parent_type_id FROM operations.finding_relationship_rules
          WHERE enabled AND kind = 'covers')
        UNION ALL
        (SELECT child_type_id, parent_type_id FROM operations.finding_relationship_rules
          WHERE enabled AND kind = 'covers'
         EXCEPT
         SELECT c.id, p.id FROM operations.finding_types c
          CROSS JOIN LATERAL jsonb_array_elements_text(c.covered_by) e(name)
          JOIN operations.finding_types p ON p.name = e.name)) d;
    IF v > 0 THEN
        RAISE EXCEPTION 'M4: % cover rules disagree with finding_types.covered_by', v;
    END IF;
END
$$;

UPDATE operations.finding_contract SET version = 4, published_at = now();
"""

REVERSE_SQL = "UPDATE operations.finding_contract SET version = 3, published_at = now();"


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0367_admin_findings_compatibility_view"),
    ]

    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
