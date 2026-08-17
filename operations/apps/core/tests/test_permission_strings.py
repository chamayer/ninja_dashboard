"""Permission strings must resolve against the app registry.

`apps/core/apps.py` sets ``label = "operations"`` while the package is
``apps.core``, and `has_perm("<app_label>.<codename>")` matches the app label
exactly. Two checks were written as ``core.…`` and could therefore never match
a real permission:

    capability.CURATOR_PERMISSION      "core.curate_software_capability"
    views (two literal copies)         "core.authorize_software_product"

The failure was invisible in every way that normally catches things.
`has_perm` short-circuits to True for superusers, so both controls worked for
the account doing the testing; for everyone else the template gate was simply
false, so the button did not render and no error was raised. Granting the
permission in the admin did not help, because the string being checked did not
name it. `manage.py check` does not validate permission strings, and the
existing tests asserted that a permission check was *present*, not that it
resolved.

These tests resolve each string the way Django does: split on the dot, require
the app label to be this app's configured label, and require the codename to be
a permission the app actually declares.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps

from apps.core import capability

# Deliberately no `django_db` marker: these resolve against the app registry,
# not against auth_permission rows. That keeps the test independent of whether
# migrations have run, and it is the stronger check -- the registry is what
# creates those rows, so a codename correct here cannot be missing there.


def _declared_codenames() -> set[str]:
    """Every permission codename this app declares.

    Django's own default per model (add/change/delete/view) plus anything in a
    model's ``Meta.permissions``. Read from the registry rather than the
    database so the test does not depend on migrations having been applied.
    """
    codenames: set[str] = set()
    app_config = django_apps.get_app_config("operations")
    for model in app_config.get_models():
        opts = model._meta
        for action in opts.default_permissions:
            codenames.add(f"{action}_{opts.model_name}")
        for codename, _label in opts.permissions:
            codenames.add(codename)
    return codenames


PERMISSION_CONSTANTS = (
    ("CURATOR_PERMISSION", capability.CURATOR_PERMISSION),
    ("AUTHORIZE_PERMISSION", capability.AUTHORIZE_PERMISSION),
)


@pytest.mark.parametrize(("name", "permission"), PERMISSION_CONSTANTS)
def test_permission_strings_resolve(name: str, permission: str) -> None:
    app_label, _, codename = permission.partition(".")
    assert codename, f"{name} must be '<app_label>.<codename>'"

    expected_label = django_apps.get_app_config("operations").label
    assert app_label == expected_label, (
        f"{name} uses app label {app_label!r}, but apps/core/apps.py declares "
        f"{expected_label!r}. has_perm matches the label exactly, so this "
        f"check can never pass for a non-superuser."
    )
    assert codename in _declared_codenames(), (
        f"{name} names codename {codename!r}, which no model in the app declares."
    )


def test_authorization_permission_has_one_definition() -> None:
    """The two literal copies in views.py are how the label drifted in the
    first place: one call site could be corrected and the other missed."""
    from pathlib import Path

    views_src = (Path(__file__).resolve().parents[1] / "views.py").read_text(encoding="utf-8")
    assert '"core.authorize_software_product"' not in views_src
    assert '"operations.authorize_software_product"' not in views_src, (
        "reference capability.AUTHORIZE_PERMISSION rather than repeating the literal"
    )
    assert views_src.count("capability_evidence.AUTHORIZE_PERMISSION") >= 2


def test_no_core_prefixed_permissions_anywhere() -> None:
    """`core.` is never a valid prefix here, whatever the codename."""
    from pathlib import Path

    app_root = Path(__file__).resolve().parents[1]
    offenders: list[str] = []
    for path in app_root.rglob("*.py"):
        if path.name == Path(__file__).name:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if '"core.' in line or "'core." in line:
                offenders.append(f"{path.relative_to(app_root)}:{number}: {line.strip()}")
    assert not offenders, "app label is 'operations', not 'core':\n" + "\n".join(offenders)
