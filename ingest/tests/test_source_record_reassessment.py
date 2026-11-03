from contextlib import contextmanager
from types import SimpleNamespace
from unittest import TestCase, mock
from uuid import UUID

from ingest import source_record_reassessment as reassessment


class ReassessmentApplyTest(TestCase):
    def test_changed_match_returns_to_review(self):
        subject, proposed, observation, instance = (UUID(int=n) for n in range(1, 5))
        cur = mock.MagicMock()
        cur.fetchone.return_value = (
            1, 0, instance, "agent", "", "", "record", observation,
            "agent.rmm", "fixture", "record", {"hostname": "host"}, None,
        )

        @contextmanager
        def transaction():
            yield cur

        entry = {
            "subject_id": str(subject), "outcome": "newly_matched",
            "candidates": [str(proposed)], "proposed_device_id": str(proposed),
            "matcher": "hostname", "input_version": 1, "association_version": 0,
        }
        with (
            mock.patch.object(reassessment.db, "transaction", transaction),
            mock.patch.object(reassessment, "record_name_short", return_value="host"),
            mock.patch.object(reassessment, "load_identity_match_policies", return_value=()),
            mock.patch.object(reassessment, "identity_entity_types", return_value={"agent.rmm"}),
            mock.patch.object(reassessment, "_resolve_match", return_value=SimpleNamespace(result=None)),
        ):
            result = reassessment.apply({"tenant_id": 1, "summary": {}, "entries": [entry]})

        self.assertEqual(result["applied"], [])
        self.assertEqual(result["returned_to_review"][0]["returned_reason"], "match changed since preview")
        self.assertFalse(any("associate_record" in call.args[0] for call in cur.execute.call_args_list))
