from datetime import timedelta
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from django.urls import reverse
from django.utils import timezone
from google_fake import FakeGoogleCalendar

from apps.events.google import client as google
from apps.events.google import crypto
from apps.events.google.views import SESSION_KEY
from apps.events.models import GoogleCalendarAccount, GoogleOAuthClient

pytestmark = pytest.mark.django_db

TOKENS = {
    "access_token": "access-1",
    "refresh_token": "refresh-1",
    "expires_in": 3599,
    "scope": " ".join(google.REQUIRED_SCOPES),
}


@pytest.fixture(autouse=True)
def _configured(settings):
    settings.GOOGLE_OAUTH_CLIENT_ID = "client-id"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "client-secret"
    settings.GOOGLE_OAUTH_REDIRECT_URI = "https://example.com/oauth/google/callback/"
    settings.GOOGLE_CALENDAR_SYNC_INLINE = True


@pytest.fixture
def fake():
    fake = FakeGoogleCalendar()
    with patch("apps.events.google.sync.get_client", return_value=fake):
        yield fake


def _connect(client):
    response = client.post(reverse("events:google_connect"))
    assert response.status_code == 302
    return response, client.session[SESSION_KEY]


def test_connect_redirects_to_google_with_state_and_pkce(client, user):
    client.force_login(user)
    response, data = _connect(client)
    query = parse_qs(urlparse(response["Location"]).query)
    assert response["Location"].startswith(google.AUTH_URL)
    assert query["state"] == [data["state"]]
    assert query["code_challenge_method"] == ["S256"]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["redirect_uri"] == ["https://example.com/oauth/google/callback/"]
    assert set(query["scope"][0].split()) == set(google.REQUIRED_SCOPES)


def test_callback_rejects_a_wrong_state(client, user):
    client.force_login(user)
    _connect(client)
    with patch("apps.events.google.views.google.exchange_code") as exchange:
        response = client.get(reverse("google_oauth_callback"), {"state": "forged", "code": "abc"})
    assert response.status_code == 302
    exchange.assert_not_called()
    assert not GoogleCalendarAccount.objects.exists()


def test_callback_connects_with_encrypted_tokens_and_the_primary_calendar(client, user, fake, note_factory):
    client.force_login(user)
    _, data = _connect(client)
    with patch("apps.events.google.views.google.exchange_code", return_value=dict(TOKENS)) as exchange:
        response = client.get(reverse("google_oauth_callback"), {"state": data["state"], "code": "abc"})

    assert response.status_code == 302
    assert response["Location"] == reverse("events:google_settings")
    assert exchange.call_args.kwargs["code_verifier"] == data["verifier"]
    account = GoogleCalendarAccount.objects.get(user=user)
    assert account.refresh_token_enc and "refresh-1" not in account.refresh_token_enc
    assert account.get_refresh_token() == "refresh-1"
    assert (account.calendar_id, account.google_email) == ("me@example.com", "me@example.com")
    assert account.last_full_sync_at is not None  # initial sync ran inline


def test_callback_without_all_scopes_revokes_and_doesnt_connect(client, user):
    client.force_login(user)
    _, data = _connect(client)
    partial = {**TOKENS, "scope": google.SCOPE_EVENTS}
    with patch("apps.events.google.views.google.exchange_code", return_value=partial), \
            patch("apps.events.google.views.google.revoke_token") as revoke:
        client.get(reverse("google_oauth_callback"), {"state": data["state"], "code": "abc"})
    revoke.assert_called_once_with("refresh-1")
    assert not GoogleCalendarAccount.objects.exists()


def test_disconnect_revokes_and_removes_the_account(client, user):
    account = GoogleCalendarAccount(user=user, calendar_id="me@example.com")
    account.set_refresh_token("refresh-1")
    account.save()
    client.force_login(user)
    with patch("apps.events.google.views.google.revoke_token") as revoke:
        client.post(reverse("events:google_disconnect"))
    revoke.assert_called_once_with("refresh-1")
    assert not GoogleCalendarAccount.objects.exists()


def test_settings_page_lists_owned_calendars(client, user, fake):
    account = GoogleCalendarAccount(user=user, calendar_id="me@example.com", calendar_summary="me@example.com")
    account.set_refresh_token("refresh-1")
    account.save()
    client.force_login(user)
    body = client.get(reverse("events:google_settings")).content.decode()
    assert "Work" in body
    assert reverse("events:google_disconnect") in body


def test_without_any_application_the_page_opens_but_connecting_is_refused(client, user, settings):
    settings.GOOGLE_OAUTH_CLIENT_ID = ""
    client.force_login(user)
    body = client.get(reverse("events:google_settings")).content.decode()
    assert "https://example.com/oauth/google/callback/" in body  # the redirect URI to register
    response = client.post(reverse("events:google_connect"))
    assert response["Location"] == reverse("events:google_settings")
    assert SESSION_KEY not in client.session


def _save_own_client(client, client_id="own-id", client_secret="own-secret"):
    return client.post(reverse("events:google_oauth_client"), {
        "action": "save", "oauth-client_id": client_id, "oauth-client_secret": client_secret,
    })


def test_own_application_is_stored_encrypted_and_never_shown(client, user):
    client.force_login(user)
    assert _save_own_client(client).status_code == 302
    record = GoogleOAuthClient.objects.get(user=user)
    assert record.client_id == "own-id"
    assert "own-secret" not in record.client_secret_enc and record.get_client_secret() == "own-secret"
    assert "own-secret" not in client.get(reverse("events:google_settings")).content.decode()

    # Same client id, blank secret: the stored secret is kept.
    _save_own_client(client, client_secret="")
    assert GoogleOAuthClient.objects.get(user=user).get_client_secret() == "own-secret"
    # Another client id needs its own secret.
    response = _save_own_client(client, client_id="other-id", client_secret="")
    assert response.status_code == 200
    assert GoogleOAuthClient.objects.get(user=user).client_id == "own-id"


def test_own_application_is_used_to_connect(client, user, fake):
    client.force_login(user)
    _save_own_client(client)
    response, data = _connect(client)
    assert parse_qs(urlparse(response["Location"]).query)["client_id"] == ["own-id"]

    with patch("apps.events.google.views.google.exchange_code", return_value=dict(TOKENS)) as exchange:
        client.get(reverse("google_oauth_callback"), {"state": data["state"], "code": "abc"})
    oauth_client = exchange.call_args.kwargs["oauth_client"]
    assert (oauth_client.client_id, oauth_client.client_secret) == ("own-id", "own-secret")
    assert GoogleCalendarAccount.objects.get(user=user).oauth_client_id == "own-id"


def test_site_application_is_the_fallback(client, user, fake):
    client.force_login(user)
    response, data = _connect(client)
    assert parse_qs(urlparse(response["Location"]).query)["client_id"] == ["client-id"]
    with patch("apps.events.google.views.google.exchange_code", return_value=dict(TOKENS)):
        client.get(reverse("google_oauth_callback"), {"state": data["state"], "code": "abc"})
    assert GoogleCalendarAccount.objects.get(user=user).oauth_client_id == "client-id"


def test_replacing_the_application_drops_a_connection_made_through_the_old_one(client, user):
    client.force_login(user)
    _save_own_client(client)
    account = GoogleCalendarAccount(user=user, calendar_id="me@example.com", oauth_client_id="own-id")
    account.set_refresh_token("refresh-1")
    account.save()
    with patch("apps.events.google.views.google.revoke_token") as revoke:
        _save_own_client(client, client_id="other-id", client_secret="other-secret")
    revoke.assert_called_once_with("refresh-1")
    account.refresh_from_db()
    assert account.status == GoogleCalendarAccount.Status.NEEDS_RECONNECT
    assert account.refresh_token_enc == ""


def test_adding_an_own_application_keeps_a_site_connection_until_reconnect(client, user, fake):
    account = GoogleCalendarAccount(user=user, calendar_id="me@example.com", oauth_client_id="client-id")
    account.set_refresh_token("refresh-1")
    account.save()
    client.force_login(user)
    _save_own_client(client)
    account.refresh_from_db()
    assert account.is_active and account.get_refresh_token() == "refresh-1"
    assert "Reconnect to switch to this one" in client.get(reverse("events:google_settings")).content.decode()


def test_removing_the_own_application_keeps_a_site_connection(client, user):
    GoogleOAuthClient.objects.create(user=user, client_id="own-id")
    account = GoogleCalendarAccount(user=user, calendar_id="me@example.com", oauth_client_id="client-id")
    account.set_refresh_token("refresh-1")
    account.save()
    client.force_login(user)
    client.post(reverse("events:google_oauth_client"), {"action": "remove"})
    assert not GoogleOAuthClient.objects.exists()
    account.refresh_from_db()
    assert account.is_active and account.get_refresh_token() == "refresh-1"


def test_profile_shows_the_connection_card(client, user):
    client.force_login(user)
    body = client.get(reverse("users:profile")).content.decode()
    assert reverse("events:google_settings") in body


def test_tokens_round_trip_and_keys_rotate(settings):
    old_key, new_key = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    settings.GOOGLE_TOKEN_ENCRYPTION_KEY = old_key
    stored = crypto.encrypt("secret")
    assert stored != "secret" and crypto.decrypt(stored) == "secret"

    settings.GOOGLE_TOKEN_ENCRYPTION_KEY = f"{new_key},{old_key}"
    assert crypto.decrypt(stored) == "secret"
    settings.GOOGLE_TOKEN_ENCRYPTION_KEY = new_key
    with pytest.raises(crypto.TokenDecryptError):
        crypto.decrypt(stored)


def test_client_refreshes_an_expired_token_and_reports_a_revoked_grant(user):
    account = GoogleCalendarAccount(user=user, calendar_id="me@example.com")
    account.set_refresh_token("refresh-1")
    account.set_access_token("stale", timezone.now() - timedelta(minutes=1))
    account.save()
    api = google.CalendarClient(account)

    token_response = Mock(status_code=200, json=Mock(return_value={"access_token": "fresh", "expires_in": 3600}))
    api_response = Mock(status_code=200, content=b"{}", json=Mock(return_value={"items": []}))
    with patch("apps.events.google.client.requests.post", return_value=token_response), \
            patch("apps.events.google.client.requests.request", return_value=api_response) as request:
        assert api.list_calendars() == []
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer fresh"
    account.refresh_from_db()
    assert account.get_access_token() == "fresh"

    account.access_token_expires_at = timezone.now() - timedelta(minutes=1)
    revoked = Mock(status_code=400, json=Mock(return_value={"error": "invalid_grant"}))
    with patch("apps.events.google.client.requests.post", return_value=revoked), pytest.raises(google.GoogleAuthError):
        api.list_calendars()


def test_refresh_goes_through_the_client_the_tokens_were_issued_to(user):
    own = GoogleOAuthClient(user=user, client_id="own-id")
    own.set_client_secret("own-secret")
    own.save()
    account = GoogleCalendarAccount(user=user, calendar_id="me@example.com", oauth_client_id="own-id")
    account.set_refresh_token("refresh-1")
    account.save()
    token_response = Mock(status_code=200, json=Mock(return_value={"access_token": "fresh", "expires_in": 3600}))
    api_response = Mock(status_code=200, content=b"{}", json=Mock(return_value={"items": []}))
    with patch("apps.events.google.client.requests.post", return_value=token_response) as post, \
            patch("apps.events.google.client.requests.request", return_value=api_response):
        google.CalendarClient(account).list_calendars()
    assert (post.call_args.kwargs["data"]["client_id"], post.call_args.kwargs["data"]["client_secret"]) == (
        "own-id", "own-secret",
    )

    # That client is gone (replaced by another one) - reconnecting is the only way.
    own.client_id = "other-id"
    own.save()
    account.access_token_expires_at = None
    with patch("apps.events.google.client.requests.post") as post, pytest.raises(google.GoogleAuthError):
        google.CalendarClient(account).list_calendars()
    post.assert_not_called()


def test_undecryptable_tokens_are_an_auth_error(user, settings):
    settings.GOOGLE_TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    account = GoogleCalendarAccount(user=user, calendar_id="me@example.com")
    account.set_refresh_token("refresh-1")
    account.save()
    settings.GOOGLE_TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()  # the old key was dropped
    with pytest.raises(google.GoogleAuthError):
        google.CalendarClient(account).list_calendars()
