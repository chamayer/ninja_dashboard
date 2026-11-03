"""Explicit client decisions retain their current contradictory evidence."""

import unittest
from uuid import UUID

from ingest.identity.computer_client_ownership import compare_explicit_client_decision

CLIENT_A = UUID(int=1)
CLIENT_B = UUID(int=2)
CLIENT_C = UUID(int=3)


class DecisionEvidenceTests(unittest.TestCase):
    def test_agreement_preserves_selected_client(self):
        result = compare_explicit_client_decision(CLIENT_A, iter([CLIENT_A, CLIENT_A]))
        self.assertEqual(result.selected_client_id, CLIENT_A)
        self.assertEqual(result.evidence.status, "resolved")
        self.assertEqual(result.contradicting_client_ids, frozenset())

    def test_unanimous_different_client_is_a_contradiction(self):
        result = compare_explicit_client_decision(CLIENT_A, [CLIENT_B])
        self.assertEqual(result.selected_client_id, CLIENT_A)
        self.assertEqual(result.evidence.client_id, CLIENT_B)
        self.assertEqual(result.contradicting_client_ids, frozenset({CLIENT_B}))

    def test_mixed_clients_report_all_distinct_contradictions(self):
        result = compare_explicit_client_decision(CLIENT_A, [CLIENT_B, CLIENT_C, CLIENT_B])
        self.assertEqual(result.evidence.status, "conflict")
        self.assertEqual(result.contradicting_client_ids, frozenset({CLIENT_B, CLIENT_C}))

    def test_unknown_evidence_is_visible_and_not_a_contradiction(self):
        result = compare_explicit_client_decision(CLIENT_A, [CLIENT_A, None])
        self.assertEqual(result.evidence.status, "unknown")
        self.assertEqual(result.evidence.unknown_record_count, 1)
        self.assertFalse(result.contradicting_client_ids)

    def test_absent_records_do_not_replace_decision(self):
        result = compare_explicit_client_decision(CLIENT_A, [])
        self.assertEqual(result.selected_client_id, CLIENT_A)
        self.assertEqual(result.evidence.status, "unknown")
        self.assertFalse(result.contradicting_client_ids)


if __name__ == "__main__":
    unittest.main()
