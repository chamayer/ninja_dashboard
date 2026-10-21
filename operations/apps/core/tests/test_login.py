from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.template.loader import get_template
from django.test import RequestFactory
from django.urls import resolve, reverse

_BASE = Path(__file__).parents[3].joinpath("templates", "base.html").read_text(encoding="utf-8")


def _anonymous(request):
    request.user = AnonymousUser()
    request.session = SessionStore()
    return request


def test_login_required_redirects_to_operations_sign_in_not_admin():
    assert settings.LOGIN_URL == reverse("login") == "/login/"
    assert resolve("/login/").func.view_class.__name__ == "LoginView"


def test_sign_in_page_renders_form_for_any_user():
    request = _anonymous(RequestFactory().get("/login/", {"next": "/inventory/computers/"}))

    response = resolve("/login/").func(request)
    response.render()
    html = response.content.decode()

    assert response.status_code == 200
    assert 'name="csrfmiddlewaretoken"' in html
    assert 'name="username"' in html
    assert 'name="password"' in html
    assert 'name="next" value="/inventory/computers/"' in html
    assert "staff account" not in html


def test_sign_out_is_post_only():
    request = _anonymous(RequestFactory().get("/logout/"))

    assert resolve("/logout/").func(request).status_code == 405
    assert reverse("login") == settings.LOGOUT_REDIRECT_URL


def test_password_change_requires_sign_in():
    request = _anonymous(RequestFactory().get("/account/password/"))

    response = resolve("/account/password/").func(request)

    assert response.status_code == 302
    assert response.url.startswith("/login/?next=")


def test_header_uses_operations_sign_in_and_post_sign_out():
    assert "admin:logout" not in _BASE
    assert "admin:login" not in _BASE
    assert '<form action="{% url \'logout\' %}" method="post"' in _BASE
    assert "{% url 'password_change' %}" in _BASE


def test_auth_templates_load():
    for name in (
        "registration/login.html",
        "registration/password_change_form.html",
        "registration/password_change_done.html",
    ):
        assert "operations" in str(get_template(name).origin.name).lower()
