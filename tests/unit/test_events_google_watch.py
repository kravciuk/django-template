from datetime import timedelta
from unittest.mock import patch

import pytest
from constance.test import override_config
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from google_fake import FakeGoogleCalendar

from apps.events import tasks
from apps.events.google import sync, watch
from apps.events.google.client import BadRequest, GoogleAuthError
from apps.events.models import GoogleCalendarAccount

pytestmark = pytest.mark.django_db

CAL = "me@example.com"
WORK = "work@group.calendar.google.com"


@pytest.fixture(autouse=True)
def _push_available(settings):
    settings.SITE_URL = "https://calendar.example.com"
    with override_config(GOOGLE_CALENDAR_PUSH_ENABLED=True), \
            patch("apps.notifications.services.push_notification"):
        yield


@pytest.fixture
def fake():
    fake = FakeGoogleCalendar()
    with patch("apps.events.google.sync.get_client", return_value=fake):
        yield fake


@pytest.fixture
def account(user):
    account = GoogleCalendarAccount(user=user, calendar_id=CAL, calendar_summary="Me", google_email=CAL)
    account.set_refresh_token("refresh-token")
    account.save()
    return account


def run(account, **kwargs):
    account.refresh_from_db()
    result = sync.sync_account(account, **kwargs)
    assert result is not None and not result.errors, result and result.errors
    account.refresh_from_db()
    return result


# --- channel lifecycle ---


def test_a_sync_opens_a_channel_to_the_webhook(account, fake):
    run(account)
    channel = fake.channels[account.watch_channel_id]
    assert channel["address"] == "https://calendar.example.com" + reverse("google_calendar_webhook")
    assert channel["token"] == account.watch_token and channel["calendar_id"] == CAL
    assert account.watch_resource_id == channel["resourceId"]
    assert watch.TTL_MIN.total_seconds() <= channel["ttl_seconds"] <= watch.TTL_MAX.total_seconds()
    assert account.is_watched
    # Watched: polling drops to the rare fallback interval (60 min +/-25%).
    assert timedelta(minutes=44) < account.next_sync_at - timezone.now() < timedelta(minutes=76)


@pytest.mark.parametrize("site_url, enabled", [("http://calendar.example.com", True), ("https://calendar.example.com", False)])
def test_no_channel_without_https_or_the_switch(account, fake, settings, site_url, enabled):
    settings.SITE_URL = site_url
    with override_config(GOOGLE_CALENDAR_PUSH_ENABLED=enabled):
        run(account)
    assert fake.channels == {} and account.watch_channel_id == ""
    assert timedelta(minutes=7) < account.next_sync_at - timezone.now() < timedelta(minutes=13)


def test_a_fresh_channel_is_kept_and_a_nearly_expired_one_renewed(account, fake):
    run(account)
    first = account.watch_channel_id
    calls = fake.calls
    run(account)
    assert account.watch_channel_id == first
    assert fake.calls == calls + 1  # just the events.list

    GoogleCalendarAccount.objects.filter(pk=account.pk).update(watch_expires_at=timezone.now() + timedelta(hours=12))
    run(account)
    assert account.watch_channel_id != first
    assert fake.stopped == [(first, f"res-{CAL}")]
    assert list(fake.channels) == [account.watch_channel_id]


def test_switching_calendars_moves_the_channel(account, fake):
    run(account)
    first = account.watch_channel_id
    sync.switch_calendar(account, WORK, "Work")
    run(account)
    assert account.watch_calendar_id == WORK
    assert fake.channels[account.watch_channel_id]["calendar_id"] == WORK
    assert fake.stopped[0][0] == first


def test_turning_push_off_stops_the_channel(account, fake):
    run(account)
    channel = account.watch_channel_id
    with override_config(GOOGLE_CALENDAR_PUSH_ENABLED=False):
        run(account)
    assert account.watch_channel_id == "" and fake.stopped[0][0] == channel


def test_a_channel_google_refuses_leaves_the_sync_on_polling(account, fake):
    fake.watch_fail_with = BadRequest("Request rejected (pushNotSupportedForRequestedResource)", 400)
    result = run(account)
    assert not result.errors
    assert account.watch_channel_id == "" and account.last_synced_at is not None


def test_a_revoked_grant_forgets_the_channel(account, fake):
    run(account)
    fake.fail_with = GoogleAuthError("invalid_grant", 400)
    account.refresh_from_db()
    sync.sync_account(account)
    account.refresh_from_db()
    assert account.status == GoogleCalendarAccount.Status.NEEDS_RECONNECT
    assert account.watch_channel_id == "" and account.watch_token == ""


def test_disconnect_stops_the_channel_before_revoking(account, fake, client, user):
    run(account)
    channel = account.watch_channel_id
    client.force_login(user)
    stopped_when_revoked = []
    with patch("apps.events.google.views.google.revoke_token") as revoke:
        revoke.side_effect = lambda token: stopped_when_revoked.extend(fake.stopped)
        client.post(reverse("events:google_disconnect"))
    assert stopped_when_revoked == [(channel, f"res-{CAL}")]


# --- webhook ---


def _notify(client, account=None, *, state="exists", **headers):
    values = {
        "HTTP_X_GOOG_CHANNEL_ID": account.watch_channel_id if account else "unknown",
        "HTTP_X_GOOG_CHANNEL_TOKEN": account.watch_token if account else "",
        "HTTP_X_GOOG_RESOURCE_ID": account.watch_resource_id if account else "",
        "HTTP_X_GOOG_RESOURCE_STATE": state,
        "HTTP_X_GOOG_MESSAGE_NUMBER": "2",
    }
    values.update(headers)
    return client.post(reverse("google_calendar_webhook"), **values)


@pytest.fixture
def queued():
    with patch("apps.events.google.webhook.queue_account_sync") as queue:
        yield queue


@pytest.fixture
def anon():
    return Client(enforce_csrf_checks=True)  # Google sends no CSRF token


def test_a_change_notification_queues_one_interactive_sync(account, fake, anon, queued):
    run(account)
    assert _notify(anon, account).status_code == 204
    assert _notify(anon, account).status_code == 204  # same burst: debounced
    queued.assert_called_once_with(account.pk, interactive=True, from_webhook=True, countdown=5)


def test_the_handshake_needs_no_sync(account, fake, anon, queued):
    run(account)
    assert _notify(anon, account, state="sync").status_code == 204
    queued.assert_not_called()


@pytest.mark.parametrize("override", [
    {"HTTP_X_GOOG_CHANNEL_TOKEN": "forged"},
    {"HTTP_X_GOOG_RESOURCE_ID": "res-someone-else"},
    {"HTTP_X_GOOG_CHANNEL_ID": "unknown"},
    {"HTTP_X_GOOG_CHANNEL_ID": ""},
])
def test_a_notification_that_doesnt_check_out_is_ignored(account, fake, anon, queued, override):
    run(account)
    assert _notify(anon, account, **override).status_code == 204
    queued.assert_not_called()


def test_a_disabled_account_ignores_notifications(account, fake, anon, queued):
    run(account)
    GoogleCalendarAccount.objects.filter(pk=account.pk).update(sync_enabled=False)
    _notify(anon, account)
    queued.assert_not_called()


def test_the_master_switch_silences_notifications(account, fake, anon, queued):
    run(account)
    with override_config(GOOGLE_CALENDAR_SYNC_ENABLED=False):
        assert _notify(anon, account).status_code == 204
    queued.assert_not_called()


def test_the_webhook_only_takes_post(anon):
    assert anon.get(reverse("google_calendar_webhook")).status_code == 405


def test_a_notified_sync_that_finds_another_running_retries_once(account, fake):
    cache.add(sync._lock_key(account), 1)
    with patch("apps.events.tasks.queue_account_sync") as queue:
        assert tasks.sync_google_calendar_account(account.pk, from_webhook=True) == "skipped"
        queue.assert_called_once_with(account.pk, interactive=True, countdown=tasks.WEBHOOK_RETRY_DELAY)
        queue.reset_mock()
        tasks.sync_google_calendar_account(account.pk)  # a scheduled one doesn't
        queue.assert_not_called()
