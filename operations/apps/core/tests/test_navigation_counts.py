"""Navigation totals keep their scope and bounded freshness, including zero."""

from __future__ import annotations

import time
import uuid
from unittest.mock import Mock

import pytest
from django.core.cache.backends.locmem import LocMemCache

from apps.core import context_processors


@pytest.mark.parametrize("badge", ["issues", "patching"])
def test_navigation_totals_cache_zero_expire_and_isolate_tenant_keys(monkeypatch, badge):
    clock = [1000.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    monkeypatch.setattr(context_processors, "cache", LocMemCache(str(uuid.uuid4()), {}))
    query = Mock(side_effect=[0, 9, 7])
    if badge == "issues":
        monkeypatch.setattr(context_processors.issue_selection, "count", query)
        load = context_processors._nav_issues_count
    else:
        filtered = Mock()
        filtered.count = query
        filter_query = Mock(return_value=filtered)
        monkeypatch.setattr(context_processors.Finding.objects, "filter", filter_query)
        load = context_processors._nav_patching_count

    assert load(1) == 0
    clock[0] += 59
    assert load(1) == 0
    assert query.call_count == 1
    assert load(2) == 9
    assert load(1) == 0
    clock[0] += 2
    assert load(1) == 7
    assert query.call_count == 3
    if badge == "issues":
        assert all(
            call.args == (context_processors.issue_selection.Scope(status="open"),)
            for call in query.call_args_list
        )
    else:
        assert [call.kwargs["tenant_id"] for call in filter_query.call_args_list] == [1, 2, 1]
        assert all(
            call.kwargs["finding_type__issue_category"] == "Patching & support"
            and call.kwargs["status__in"] == context_processors._FINDING_ACTIVE_STATUSES
            for call in filter_query.call_args_list
        )
