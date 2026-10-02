from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from constance.test import override_config
from django.utils import timezone

from apps.content.enums import NoteKind
from apps.events.recurrence import all_day_moment
from apps.events.reminders import REMINDED_AT_KEY, next_reminder_at
from apps.events.tasks import send_due_reminders
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _no_websocket_push():
    with patch("apps.notifications.services.push_notification"):
        yield


def test_single_event_reminder(user, note_factory):
    note = note_factory(title="Call", starts_at=NOW + timedelta(hours=2), remind_minutes_before=15)
    assert next_reminder_at(note, NOW) == NOW + timedelta(hours=2) - timedelta(minutes=15)
    assert next_reminder_at(note, NOW + timedelta(hours=3)) is None


def test_no_offset_means_no_reminder_for_notes(user, note_factory):
    note = note_factory(title="Call", starts_at=NOW + timedelta(hours=2))
    assert next_reminder_at(note, NOW) is None


def test_recurring_event_reminds_before_the_next_occurrence(user, note_factory):
    note = note_factory(title="Birthday", starts_at=datetime(2020, 3, 10, 9, tzinfo=UTC),
                        recurrence="FREQ=YEARLY", remind_minutes_before=24 * 60)
    assert next_reminder_at(note, NOW) == datetime(2027, 3, 9, 9, tzinfo=UTC)


def test_all_day_event_anchors_at_owner_local_midnight(user, note_factory):
    user.timezone = "Europe/Vilnius"
    user.save()
    note = note_factory(title="Trip", all_day=True, starts_at=all_day_moment(date(2026, 10, 10)),
                        remind_minutes_before=0)
    # Midnight in Vilnius (UTC+3 in October) is 21:00 UTC the day before.
    assert next_reminder_at(note, NOW) == datetime(2026, 10, 9, 21, tzinfo=UTC)


@override_config(EVENTS_DOCUMENT_REMIND_DAYS=14)
def test_documents_use_the_default_lead_unless_they_set_their_own(user, note_factory):
    expires = NOW + timedelta(days=30)
    document = note_factory(title="Warranty", kind=NoteKind.WARRANTY, expires_at=expires)
    assert next_reminder_at(document, NOW) == expires - timedelta(days=14)
    document.remind_minutes_before = 60
    assert next_reminder_at(document, NOW) == expires - timedelta(minutes=60)


@override_config(EVENTS_DOCUMENT_REMIND_DAYS=0)
def test_document_default_can_be_turned_off(user, note_factory):
    document = note_factory(title="Warranty", kind=NoteKind.WARRANTY, expires_at=NOW + timedelta(days=30))
    assert next_reminder_at(document, NOW) is None


def test_drafts_never_get_a_reminder(user, note_factory):
    note = note_factory(title="Draft", is_draft=True, starts_at=NOW + timedelta(hours=2), remind_minutes_before=15)
    assert next_reminder_at(note, NOW) is None


def test_save_signal_sets_remind_at(user, note_factory):
    starts = timezone.now() + timedelta(days=1)
    note = note_factory(title="Call", starts_at=starts, remind_minutes_before=60)
    note.refresh_from_db()
    assert note.remind_at == starts - timedelta(minutes=60)

    note.remind_minutes_before = None
    note.save()
    note.refresh_from_db()
    assert note.remind_at is None


def _make_due(note, at):
    type(note).objects.filter(pk=note.pk).update(remind_at=at)
    note.refresh_from_db()


def test_task_sends_notification_and_clears_single_reminder(user, note_factory):
    starts = timezone.now() + timedelta(minutes=10)
    note = note_factory(title="Dentist", starts_at=starts, remind_minutes_before=15)
    note.refresh_from_db()
    assert note.remind_at <= timezone.now()  # 15 min before something 10 min away

    assert send_due_reminders() == 1

    notification = Notification.objects.get(recipient=user)
    assert notification.payload["title"] == "Dentist"
    assert notification.payload["url"].endswith(f"{note.public_id}/")
    note.refresh_from_db()
    assert note.remind_at is None
    assert note.json_data[REMINDED_AT_KEY]
    # A save right after delivery must not schedule the same reminder again.
    note.save()
    note.refresh_from_db()
    assert note.remind_at is None
    assert send_due_reminders() == 0


def test_task_advances_recurring_reminder(user, note_factory):
    now = timezone.now()
    note = note_factory(title="Standup", starts_at=now + timedelta(minutes=5),
                        recurrence="FREQ=DAILY", remind_minutes_before=10)
    note.refresh_from_db()
    first = note.remind_at
    assert first <= now

    assert send_due_reminders() == 1

    note.refresh_from_db()
    assert note.remind_at == first + timedelta(days=1)


def test_task_skips_reminders_whose_settings_changed(user, note_factory):
    note = note_factory(title="Call", starts_at=timezone.now() + timedelta(days=1))
    _make_due(note, timezone.now() - timedelta(minutes=1))  # stale: note has no offset

    assert send_due_reminders() == 0
    assert not Notification.objects.exists()
    note.refresh_from_db()
    assert note.remind_at is None


def test_task_ignores_drafts_and_trash(user, note_factory):
    trashed = note_factory(title="Trashed", starts_at=timezone.now() + timedelta(minutes=5), remind_minutes_before=10)
    trashed.soft_delete()
    assert send_due_reminders() == 0
