from datetime import timedelta
from unittest.mock import Mock, patch

import pytest
from constance.test import override_config
from django.utils import timezone
from google_fake import FakeGoogleCalendar

from apps.common.enums import ContentFormat
from apps.events.google import client as google
from apps.events.google import ratelimit, sync
from apps.events.models import GoogleCalendarAccount

pytestmark = pytest.mark.django_db


@pytest.fixture
def account(user):
    account = GoogleCalendarAccount(user=user, calendar_id="me@example.com", oauth_client_id="client-a")
    account.set_refresh_token("refresh-token")
    account.set_access_token("access", timezone.now() + timedelta(hours=1))
    account.save()
    return account


def _api_response(status=200, reason=None, headers=None):
    body = {"error": {"errors": [{"reason": reason}]}} if reason else {"items": []}
    return Mock(status_code=status, content=b"{}", headers=headers or {}, json=Mock(return_value=body))


@override_config(GOOGLE_CALENDAR_MAX_REQUESTS_PER_MINUTE=3)
def test_the_budget_is_per_oauth_client():
    assert [ratelimit.acquire("client-a") for _ in range(3)] == [0, 0, 0]
    assert 0 < ratelimit.acquire("client-a") <= ratelimit.WINDOW_SECONDS
    assert ratelimit.acquire("client-b") == 0  # a user's own client has its own quota


@override_config(GOOGLE_CALENDAR_MAX_REQUESTS_PER_MINUTE=1)
def test_a_used_up_budget_stops_requests_before_they_reach_google(account):
    api = google.CalendarClient(account)
    with patch("apps.events.google.client.requests.request", return_value=_api_response()) as request:
        api.list_calendars()
        with pytest.raises(google.QuotaPaused):
            api.list_calendars()
    assert request.call_count == 1


def test_a_project_quota_error_pauses_every_account_on_the_client(account):
    api = google.CalendarClient(account)
    with patch("apps.events.google.client.requests.request", return_value=_api_response(403, "userRateLimitExceeded")):
        with pytest.raises(google.QuotaPaused):
            api.list_calendars()
    assert ratelimit.paused("client-a")
    assert not ratelimit.paused("client-b")


def test_a_per_user_rate_limit_only_backs_this_account_off(account):
    api = google.CalendarClient(account)
    with patch("apps.events.google.client.requests.request", return_value=_api_response(403, "rateLimitExceeded")):
        with pytest.raises(google.GoogleRateLimited) as exc_info:
            api.list_calendars()
    assert not isinstance(exc_info.value, google.QuotaPaused)
    assert not ratelimit.paused("client-a")


def test_a_paused_sync_is_postponed_not_counted_as_a_failure(account, note_factory):
    fake = FakeGoogleCalendar()
    fake.fail_with = google.QuotaPaused("budget used up", retry_after=20)
    note_factory(title="Waiting", body_format=ContentFormat.PLAIN, starts_at=timezone.now() + timedelta(days=1))
    with patch("apps.events.google.sync.get_client", return_value=fake):
        result = sync.sync_account(account)
    assert result.errors
    account.refresh_from_db()
    assert (account.consecutive_failures, account.retry_after, account.last_error) == (0, None, "")
    assert account.status == GoogleCalendarAccount.Status.ACTIVE
    assert timedelta(seconds=19) < account.next_sync_at - timezone.now() < timedelta(seconds=51)
    assert account.push_pending  # nothing was pushed - still to do


def test_a_push_cut_short_keeps_its_changes_pending(account, note_factory):
    fake = FakeGoogleCalendar()
    note_factory(title="First", body_format=ContentFormat.PLAIN, starts_at=timezone.now() + timedelta(days=1))
    note_factory(title="Second", body_format=ContentFormat.PLAIN, starts_at=timezone.now() + timedelta(days=2))
    with patch("apps.events.google.sync.get_client", return_value=fake), \
            override_config(GOOGLE_CALENDAR_MAX_WRITES_PER_RUN=1):
        assert sync.sync_account(account).inserted == 1
        account.refresh_from_db()
        assert account.push_pending
        assert sync.sync_account(account).inserted == 1
        account.refresh_from_db()
        assert not account.push_pending
