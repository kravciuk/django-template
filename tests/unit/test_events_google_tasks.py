from datetime import timedelta
from unittest.mock import patch

import pytest
from constance.test import override_config
from django.core.cache import cache
from cryptography.fernet import Fernet
from django.utils import timezone

from apps.events import tasks
from apps.events.models import GoogleCalendarAccount

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _configured(settings):
    settings.GOOGLE_OAUTH_CLIENT_ID = "client-id"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "client-secret"


def _account(user, **fields):
    fields.setdefault("calendar_id", "me@example.com")
    return GoogleCalendarAccount.objects.create(user=user, **fields)


def test_only_due_accounts_are_queued(user, other_user, django_user_model):
    now = timezone.now()
    due = _account(user, next_sync_at=now - timedelta(minutes=1), next_reconcile_at=now + timedelta(hours=5))
    _account(other_user, next_sync_at=now + timedelta(minutes=2))
    third = django_user_model.objects.create_user("carol", "carol@example.com", "pw12345678")
    _account(third, retry_after=now + timedelta(minutes=5))

    with patch.object(tasks.sync_google_calendar_account, "apply_async") as apply_async:
        assert tasks.sync_google_calendars() == 1
    apply_async.assert_called_once()
    assert apply_async.call_args.args[0] == (due.pk,)
    assert apply_async.call_args.args[1]["reconcile"] is False
    assert apply_async.call_args.kwargs["queue"] == tasks.GOOGLE_BULK_QUEUE


def test_reconnect_needed_and_disabled_accounts_are_skipped(user, other_user):
    _account(user, status=GoogleCalendarAccount.Status.NEEDS_RECONNECT)
    _account(other_user, sync_enabled=False)
    with patch.object(tasks.sync_google_calendar_account, "apply_async") as apply_async:
        assert tasks.sync_google_calendars() == 0
        assert tasks.reconcile_google_calendars() == 0
    apply_async.assert_not_called()


@override_config(GOOGLE_CALENDAR_SYNC_ENABLED=False)
def test_master_switch_stops_everything(user):
    _account(user)
    with patch.object(tasks.sync_google_calendar_account, "delay") as delay:
        assert tasks.sync_google_calendars() == 0
        assert tasks.push_notes_to_google([1]) == 0
    delay.assert_not_called()


def test_push_skips_accounts_syncing_only_from_google(user, note_factory):
    _account(user, sync_direction=GoogleCalendarAccount.SyncDirection.FROM_GOOGLE)
    note = note_factory(title="Local")
    with patch("apps.events.google.sync.get_client") as get_client:
        assert tasks.push_notes_to_google([note.pk]) == 0
    get_client.assert_not_called()


def test_sync_task_survives_undecryptable_tokens(user, settings):
    settings.GOOGLE_TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    account = GoogleCalendarAccount(user=user, calendar_id="me@example.com")
    account.set_refresh_token("refresh-1")
    account.save()
    settings.GOOGLE_TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    with patch("apps.notifications.services.push_notification"):
        tasks.sync_google_calendar_account(account.pk)
    account.refresh_from_db()
    assert account.status == GoogleCalendarAccount.Status.NEEDS_RECONNECT


def test_a_queued_account_isnt_queued_again_until_its_task_starts(user):
    account = _account(user)
    with patch.object(tasks.sync_google_calendar_account, "apply_async") as apply_async:
        assert tasks.sync_google_calendars() == 1
        assert tasks.sync_google_calendars() == 0  # the queue is lagging
    assert apply_async.call_count == 1
    with patch("apps.events.google.sync.sync_account", return_value=None):
        tasks.sync_google_calendar_account(account.pk)
    assert cache.get(tasks._queued_key(account.pk)) is None


@override_config(GOOGLE_CALENDAR_DISPATCH_BATCH=1)
def test_dispatch_is_capped_oldest_first(user, other_user):
    now = timezone.now()
    _account(user, next_sync_at=now - timedelta(minutes=1))
    oldest = _account(other_user, next_sync_at=now - timedelta(minutes=30))
    with patch.object(tasks.sync_google_calendar_account, "apply_async") as apply_async:
        assert tasks.sync_google_calendars() == 1
    assert apply_async.call_args.args[0] == (oldest.pk,)


def test_a_due_reconcile_is_dispatched_even_between_syncs(user):
    now = timezone.now()
    account = _account(user, next_sync_at=now + timedelta(minutes=30), next_reconcile_at=now - timedelta(minutes=1))
    with patch.object(tasks.sync_google_calendar_account, "apply_async") as apply_async:
        assert tasks.sync_google_calendars() == 1
    assert apply_async.call_args.args == ((account.pk,), {"full": False, "reconcile": True, "from_webhook": False})


def test_reconcile_by_hand_makes_every_account_due(user):
    account = _account(user, next_reconcile_at=timezone.now() + timedelta(hours=10))
    assert tasks.reconcile_google_calendars() == 1
    account.refresh_from_db()
    assert account.next_reconcile_at <= timezone.now()
