"""Raise the governed Jobs concurrency ceiling to three."""

from __future__ import annotations
from typing import ClassVar
from django.db import migrations

FORWARD_SQL = r"""
ALTER TABLE operations.job_lane_limits DROP CONSTRAINT IF EXISTS job_lane_limits_capacity_check;
ALTER TABLE operations.job_lane_limits ADD CONSTRAINT job_lane_limits_capacity_check CHECK (capacity BETWEEN 1 AND 3);
ALTER TABLE operations.job_resource_limits DROP CONSTRAINT IF EXISTS job_resource_limits_capacity_check;
ALTER TABLE operations.job_resource_limits ADD CONSTRAINT job_resource_limits_capacity_check CHECK (capacity BETWEEN 1 AND 3);
UPDATE operations.job_lane_limits SET capacity=3,
    policy_revision='2e75df0042f45782259a7f3a8dbb9cff1c9b54cbe8c2fb6f97beac43c6d3a8aa'
WHERE tenant_id=1;
UPDATE operations.job_resource_limits SET capacity=3,
    policy_revision='2e75df0042f45782259a7f3a8dbb9cff1c9b54cbe8c2fb6f97beac43c6d3a8aa'
WHERE resource_template='execution:deployment';
CREATE OR REPLACE FUNCTION operations.jobs_set_capacity_v1(p_tenant_id BIGINT, p_kind TEXT, p_key TEXT, p_capacity SMALLINT)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = operations, pg_temp AS $$
BEGIN
 IF p_tenant_id <> 1 OR p_capacity NOT BETWEEN 1 AND 3 THEN RAISE EXCEPTION 'Invalid Jobs capacity policy'; END IF;
 IF p_kind = 'lane' THEN
   UPDATE job_lane_limits SET capacity=p_capacity,
       policy_revision='1a09f6c5e9935b4254174455fba24461ddc7a6fa0d50893996373fd1bdcb26ae'
   WHERE tenant_id=p_tenant_id AND lane=p_key;
 ELSIF p_kind = 'resource' THEN
   UPDATE job_resource_limits SET capacity=p_capacity,
       policy_revision='1a09f6c5e9935b4254174455fba24461ddc7a6fa0d50893996373fd1bdcb26ae'
   WHERE resource_template=p_key;
 ELSE RAISE EXCEPTION 'Unknown Jobs capacity policy kind'; END IF;
 IF NOT FOUND THEN RAISE EXCEPTION 'Unknown Jobs capacity policy'; END IF;
END; $$;
ALTER FUNCTION operations.jobs_set_capacity_v1(BIGINT, TEXT, TEXT, SMALLINT) OWNER TO operations_migrate;
REVOKE ALL ON FUNCTION operations.jobs_set_capacity_v1(BIGINT, TEXT, TEXT, SMALLINT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION operations.jobs_set_capacity_v1(BIGINT, TEXT, TEXT, SMALLINT) TO operations_app;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list[tuple[str, str]]] = [
        ("operations", "0253_patch_full_reconciliation")
    ]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, migrations.RunSQL.noop)]
