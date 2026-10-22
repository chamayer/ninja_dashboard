import inspect
import uuid
from contextlib import nullcontext
from types import SimpleNamespace
from unittest import mock

from django.test import RequestFactory

from apps.core import views


def test_accepting_a_candidate_anchors_the_new_client_to_its_entity():
    """Production 500: clients.entity_id is required (migration 0120)."""
    candidate = SimpleNamespace(
        id=uuid.uuid4(),
        display_name="Rize NYC",
        normalized_name="rizenyc",
        source_refs=[{"source_id": 2, "external_id": "77"}],
        save=mock.Mock(),
    )
    entity = SimpleNamespace(id=uuid.uuid4())
    request = RequestFactory().post("/x", {"display_name": "Rize NYC"})
    request.user = SimpleNamespace(get_username=lambda: "operator")
    accept = inspect.unwrap(views.client_candidate_accept)
    cursor = mock.MagicMock()
    with (
        mock.patch.object(views, "get_object_or_404", return_value=candidate),
        mock.patch.object(views.RequirementProfile, "objects") as profiles,
        mock.patch.object(views.Client, "objects") as clients,
        mock.patch.object(views.Entity, "objects") as entities,
        mock.patch.object(views.ClientNameAlias, "objects"),
        mock.patch.object(views.connection, "cursor", return_value=nullcontext(cursor)),
        mock.patch.object(views, "_attach_group_to_client") as attach,
        mock.patch.object(views, "_audit"),
        mock.patch.object(views, "messages"),
    ):
        profiles.filter.return_value.first.return_value = None
        clients.filter.return_value.exists.return_value = False
        entities.create.return_value = entity
        clients.create.return_value = SimpleNamespace(id=entity.id)
        accept(request, candidate.id)

    entities.create.assert_called_once()
    created_entity = entities.create.call_args.kwargs
    assert created_entity["entity_class_id"] == "client"
    assert created_entity["scope_kind"] == views.Entity.ScopeKind.TENANT
    created_client = clients.create.call_args.kwargs
    assert created_client["entity"] is entity and created_client["id"] == entity.id
    attach.assert_called_once_with(cursor, 2, "77", entity.id)
