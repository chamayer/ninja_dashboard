"""Give the protected Coverage publisher SELECT on its five missing inputs."""

from typing import ClassVar

from django.db import migrations

FORWARD_SQL = """
GRANT SELECT ON
    operations.agents,
    operations.computer_client_ownership,
    operations.device_operator_decisions,
    operations.device_requirement_state,
    operations.device_session_current
TO operations_view_owner;
"""

REVERSE_SQL = """
REVOKE SELECT ON
    operations.agents,
    operations.computer_client_ownership,
    operations.device_operator_decisions,
    operations.device_requirement_state,
    operations.device_session_current
FROM operations_view_owner;
"""


class Migration(migrations.Migration):
    dependencies: ClassVar[list] = [("operations", "0423_coverage_jobs_resource_policy")]
    operations: ClassVar[list] = [migrations.RunSQL(FORWARD_SQL, REVERSE_SQL)]
