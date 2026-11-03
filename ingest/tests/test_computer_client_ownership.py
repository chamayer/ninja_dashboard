"""The source-client evidence contract cannot resolve from partial or mixed evidence."""

from uuid import UUID

import pytest

from ingest.identity.computer_client_ownership import classify_source_clients

CLIENT_A = UUID(int=1)
CLIENT_B = UUID(int=2)


@pytest.mark.parametrize(
    ("records", "status", "client", "known", "unknown"),
    [
        ([], "unknown", None, 0, 0),
        ([None], "unknown", None, 0, 1),
        ([CLIENT_A], "resolved", CLIENT_A, 1, 0),
        ([CLIENT_A, CLIENT_A], "resolved", CLIENT_A, 1, 0),
        ([CLIENT_A, None], "unknown", None, 1, 1),
        ([CLIENT_A, CLIENT_B], "conflict", None, 2, 0),
        ([CLIENT_A, CLIENT_B, None], "conflict", None, 2, 1),
    ],
)
def test_current_record_evidence(records, status, client, known, unknown):
    result = classify_source_clients(iter(records))
    assert (result.status, result.client_id) == (status, client)
    assert (result.known_client_count, result.unknown_record_count) == (known, unknown)
