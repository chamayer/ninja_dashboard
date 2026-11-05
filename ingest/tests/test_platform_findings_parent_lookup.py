import unittest

from ingest.platform_findings import (
    _active_jobs_dependency_parent,
    _active_jobs_dependency_parents,
)


class Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def execute(self, sql, params):
        self.executed.append((sql, params))

    def fetchall(self):
        return self.rows


class DependencyParentLookupTests(unittest.TestCase):
    def test_dependency_parents_are_loaded_once_with_existing_priority(self):
        cursor = Cursor(
            [
                ("timeout:run-1", "jobs_timeout", "run-1", "job-a"),
                ("repeated:job-a", "jobs_repeated_failure", None, "job-a"),
                ("schedule:job-a", "jobs_schedule_failure", None, "job-a"),
            ]
        )

        by_run, by_job = _active_jobs_dependency_parents(cursor)

        self.assertEqual(len(cursor.executed), 1)
        sql, params = cursor.executed[0]
        self.assertIn("operations.admin_findings", sql)
        self.assertIn("ORDER BY CASE finding_type.name", sql)
        self.assertEqual(params, (1,))
        self.assertEqual(
            _active_jobs_dependency_parent(
                {"prerequisite_job_run_id": "run-1", "prerequisite_job_key": "job-a"},
                parents_by_run=by_run,
                parents_by_job=by_job,
            ),
            ("timeout:run-1", "jobs_timeout"),
        )
        self.assertEqual(
            _active_jobs_dependency_parent(
                {"prerequisite_job_run_id": "run-2", "prerequisite_job_key": "job-a"},
                parents_by_run=by_run,
                parents_by_job=by_job,
            ),
            ("repeated:job-a", "jobs_repeated_failure"),
        )
        self.assertIsNone(
            _active_jobs_dependency_parent(
                {"prerequisite_job_run_id": "", "prerequisite_job_key": "job-missing"},
                parents_by_run=by_run,
                parents_by_job=by_job,
            )
        )
