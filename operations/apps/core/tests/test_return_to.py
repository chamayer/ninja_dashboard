import uuid
from types import SimpleNamespace

from django.test import RequestFactory

from apps.core.views import _candidate_detail_redirect, _local_path


def test_local_path_accepts_only_paths_on_this_site():
    assert _local_path("/inventory/clients/?q=a") == "/inventory/clients/?q=a"
    assert _local_path("https://evil.example/") == ""
    assert _local_path("//evil.example/") == ""
    assert _local_path("") == ""
    assert _local_path(None) == ""


def test_candidate_detail_redirect_keeps_where_the_operator_came_from():
    candidate = SimpleNamespace(id=uuid.UUID("be1f50a5-c558-45bd-8911-2c819c480371"))
    request = RequestFactory().post("/x", {"next": "/?a=1"})
    assert _candidate_detail_redirect(request, candidate).url == (
        f"/clients/candidates/{candidate.id}/?next=%2F%3Fa%3D1"
    )
    plain = RequestFactory().post("/x")
    assert (
        _candidate_detail_redirect(plain, candidate).url == f"/clients/candidates/{candidate.id}/"
    )
    unsafe = RequestFactory().post("/x", {"next": "https://evil.example/"})
    assert (
        _candidate_detail_redirect(unsafe, candidate).url == f"/clients/candidates/{candidate.id}/"
    )
