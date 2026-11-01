"""Issue review evidence: OS installations that sources place on different Computers."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest import mock

from apps.core import views
from apps.core.models import Finding


def test_an_issue_without_computers_does_not_query():
    finding = SimpleNamespace(subject_type=Finding.SubjectType.CLIENT, subject_id=uuid.uuid4())
    with mock.patch.object(views, "connection") as connection:
        assert views._os_installation_disagreements(finding, {"candidate_device_ids": ["x"]}) == []
    connection.cursor.assert_not_called()


def test_the_subject_and_candidate_computers_are_both_checked():
    subject, candidate = uuid.uuid4(), uuid.uuid4()
    finding = SimpleNamespace(subject_type=Finding.SubjectType.DEVICE, subject_id=subject)
    cursor = mock.MagicMock()
    cursor.fetchall.return_value = []
    with (
        mock.patch.object(views, "connection") as connection,
        mock.patch.object(views.transaction, "atomic"),
    ):
        connection.cursor.return_value.__enter__.return_value = cursor
        assert (
            views._os_installation_disagreements(
                finding, {"candidate_device_ids": [str(candidate)]}
            )
            == []
        )
    params = cursor.execute.call_args_list[-1].args[1]
    assert sorted(params[0]) == sorted([str(subject), str(candidate)])
