"""Tests for the django-allauth-based login/signup/2FA flow (apps.users,
core/settings/auth.py, core/settings/constance.py, core/urls.py). See
docs/apps/users.md.
"""

import importlib

import pytest
from allauth.account.models import EmailAddress
from allauth.mfa.totp.internal.auth import TOTP, format_hotp_value, hotp_value, yield_hotp_counters_from_time
from constance import config
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core import mail
from django.urls import reverse

User = get_user_model()


def _verify_email(user):
    return EmailAddress.objects.create(user=user, email=user.email, verified=True, primary=True)


def _totp_code(secret):
    counter = next(yield_hotp_counters_from_time())
    return format_hotp_value(hotp_value(secret, counter))


@pytest.mark.django_db
def test_login_by_username(client, user):
    _verify_email(user)
    response = client.post(reverse("account_login"), {"login": user.username, "password": "password123"})
    assert response.status_code == 302
    assert "_auth_user_id" in client.session


@pytest.mark.django_db
def test_login_by_email(client, user):
    _verify_email(user)
    response = client.post(reverse("account_login"), {"login": user.email, "password": "password123"})
    assert response.status_code == 302
    assert "_auth_user_id" in client.session


@pytest.mark.django_db
def test_login_wrong_password_fails(client, user):
    _verify_email(user)
    response = client.post(reverse("account_login"), {"login": user.username, "password": "wrong"})
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_login_rate_limited_after_repeated_failures(client, user):
    # ACCOUNT_RATE_LIMITS["login_failed"] = "5/5m/ip,5/5m/key" (core/settings/auth.py).
    # Surfaces as a form validation error (200), not a 429 - login's rate
    # limit check runs inside the adapter's pre_authenticate(), which raises
    # a ValidationError the LoginForm renders normally; the 429 status only
    # applies to views that call ratelimit.consume_or_429() directly (e.g.
    # signup, password reset).
    _verify_email(user)
    for _ in range(5):
        client.post(reverse("account_login"), {"login": user.username, "password": "wrong"})
    response = client.post(reverse("account_login"), {"login": user.username, "password": "wrong"})
    assert response.status_code == 200
    assert b"Too many failed login attempts" in response.content


@pytest.mark.django_db
def test_remember_me_unchecked_expires_at_browser_close(client, user):
    _verify_email(user)
    client.post(reverse("account_login"), {"login": user.username, "password": "password123"})
    assert client.session.get_expire_at_browser_close() is True


@pytest.mark.django_db
def test_remember_me_checked_persists_session(client, user):
    _verify_email(user)
    client.post(
        reverse("account_login"),
        {"login": user.username, "password": "password123", "remember": "on"},
    )
    assert client.session.get_expire_at_browser_close() is False


@pytest.mark.django_db
def test_logout_via_post(client, user):
    _verify_email(user)
    client.force_login(user)
    response = client.post(reverse("account_logout"))
    assert response.status_code == 302
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_signup_closed_by_default(client):
    response = client.get(reverse("account_signup"))
    assert response.status_code == 200
    assert b"currently closed" in response.content


@pytest.mark.django_db
def test_signup_sends_confirmation_and_records_registration_ip(client):
    # ACCOUNT_ALLOW_SIGNUP is a constance setting (core/settings/constance.py),
    # not a static Django setting - override_settings doesn't touch it.
    config.ACCOUNT_ALLOW_SIGNUP = True
    response = client.post(
        reverse("account_signup"),
        {
            "email": "new.user@example.com",
            "username": "newuser",
            "password1": "a-strong-password-123",
            "password2": "a-strong-password-123",
        },
    )
    assert response.status_code == 302
    new_user = User.objects.get(username="newuser")
    assert new_user.registration_ip is not None
    assert len(mail.outbox) == 1
    assert "new.user@example.com" in mail.outbox[0].to[0]
    # Mandatory email verification (ACCOUNT_EMAIL_VERIFICATION) - not logged
    # in yet, since the address hasn't been confirmed.
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_password_reset_sends_email(client, user):
    _verify_email(user)
    response = client.post(reverse("account_reset_password"), {"email": user.email})
    assert response.status_code == 302
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_last_login_ip_recorded_on_login(client, user):
    _verify_email(user)
    assert user.last_login_ip is None
    client.post(reverse("account_login"), {"login": user.username, "password": "password123"})
    user.refresh_from_db()
    assert user.last_login_ip is not None
    assert user.last_login_date is not None


@pytest.mark.django_db
def test_admin_login_redirects_to_allauth_login(client):
    response = client.get("/admin/login/")
    assert response.status_code == 302
    assert reverse("account_login") in response.url


@pytest.mark.django_db
def test_mfa_challenge_required_on_login(client, user):
    _verify_email(user)
    totp = TOTP.activate(user, "JBSWY3DPEHPK3PXP")
    response = client.post(reverse("account_login"), {"login": user.username, "password": "password123"})
    # Password was correct, but the account has TOTP active - allauth stages
    # the login and requires a second factor before django.contrib.auth.login()
    # actually fires (see core/asgi.py's JWTAuthMiddleware for the unrelated
    # websocket auth path, not involved here).
    assert response.status_code == 302
    assert reverse("mfa_authenticate") in response.url
    assert "_auth_user_id" not in client.session

    code = _totp_code("JBSWY3DPEHPK3PXP")
    response = client.post(reverse("mfa_authenticate"), {"code": code})
    assert response.status_code == 302
    assert "_auth_user_id" in client.session
    del totp  # only kept above for readability of what the fixture set up


@pytest.mark.django_db
def test_profile_view_updates_name(client, user):
    client.force_login(user)
    response = client.post(
        reverse("users:profile"),
        {"first_name": "Alice", "last_name": "Doe"},
    )
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.first_name == "Alice"
    assert user.last_name == "Doe"


@pytest.mark.django_db
def test_profile_view_requires_login(client):
    response = client.get(reverse("users:profile"))
    assert response.status_code == 302
    assert reverse("account_login") in response.url


@pytest.mark.django_db
def test_backfill_email_addresses_migration(user):
    # apps/users/migrations/0002_backfill_email_addresses.py - exercised
    # directly against the real model state rather than a full migration-
    # history replay, since the migration itself is a plain RunPython with
    # no schema change to step through.
    EmailAddress.objects.filter(user=user).delete()
    migration = importlib.import_module("apps.users.migrations.0002_backfill_email_addresses")
    migration.backfill_email_addresses(django_apps, None)

    email = EmailAddress.objects.get(user=user)
    assert email.email == user.email
    assert email.verified is True
    assert email.primary is True
