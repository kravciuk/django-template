from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from constance.test import override_config
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone
from google_fake import FakeGoogleCalendar, all_day, timed

from apps.common.enums import ContentFormat, Visibility
from apps.content.enums import NoteKind
from apps.content.models import Note
from apps.events.google import sync
from apps.events.google.client import GoogleAuthError, GoogleServerError
from apps.events.models import GoogleCalendarAccount, GoogleEventLink
from apps.events.services import get_events_hub
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db

CAL = "me@example.com"
SOON = timezone.now().replace(microsecond=0) + timedelta(days=3)


@pytest.fixture(autouse=True)
def _no_websocket_push():
    with patch("apps.notifications.services.push_notification"):
        yield


@pytest.fixture
def fake():
    fake = FakeGoogleCalendar()
    with patch("apps.events.google.sync.get_client", return_value=fake):
        yield fake


@pytest.fixture
def account(user):
    user.timezone = "Europe/Vilnius"
    user.save()
    account = GoogleCalendarAccount(user=user, calendar_id=CAL, calendar_summary="Me", google_email=CAL)
    account.set_refresh_token("refresh-token")
    account.save()
    return account


def run(account, **kwargs):
    account.refresh_from_db()
    result = sync.sync_account(account, **kwargs)
    assert result is not None
    assert not result.errors, result.errors
    return result


def iso(moment):
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_local_note_is_inserted_once_and_then_left_alone(account, fake, note_factory):
    note = note_factory(title="Dentist", body_format=ContentFormat.PLAIN, starts_at=SOON, expires_at=SOON + timedelta(hours=1))

    result = run(account)
    assert result.inserted == 1
    event = fake.get(CAL, note.public_id.hex)
    assert event["summary"] == "Dentist"
    assert event["extendedProperties"]["private"]["note"] == str(note.public_id)

    updated_at = Note.objects.get(pk=note.pk).updated_at
    writes = len(fake.writes)
    result = run(account)
    assert len(fake.writes) == writes  # our own insert echoed back: no-op
    assert Note.objects.get(pk=note.pk).updated_at == updated_at
    assert result.created == result.updated == 0


def test_google_event_is_imported_as_a_private_quick_note(account, fake):
    fake.add_remote(CAL, {"summary": "Concert", "description": "Bring tickets", **timed(
        (SOON + timedelta(hours=18)).isoformat(), (SOON + timedelta(hours=20)).isoformat(),
    )})

    result = run(account)
    assert result.created == 1
    note = Note.objects.get(title="Concert")
    assert (note.kind, note.body_format, note.visibility, note.is_draft) == (
        NoteKind.EVENT, ContentFormat.PLAIN, Visibility.PRIVATE, False,
    )
    assert note.body == "Bring tickets"
    assert note.get_parent() == get_events_hub(note.owner)
    assert GoogleEventLink.objects.get(note=note).origin == GoogleEventLink.Origin.GOOGLE

    writes = len(fake.writes)
    run(account)
    assert len(fake.writes) == writes
    assert Note.objects.filter(title="Concert").count() == 1


def test_local_edit_patches_only_the_changed_fields(account, fake, note_factory):
    note = note_factory(title="Dentist", body_format=ContentFormat.PLAIN, starts_at=SOON)
    run(account)

    note.refresh_from_db()
    note.title = "Dentist (moved)"
    note.save()
    result = run(account)

    assert result.patched == 1
    method, _cal, event_id, body = fake.writes[-1]
    assert (method, event_id) == ("patch", note.public_id.hex)
    assert body == {"summary": "Dentist (moved)"}


def test_remote_edit_updates_the_note_without_pushing_back(account, fake, note_factory):
    note = note_factory(title="Dentist", body_format=ContentFormat.PLAIN, starts_at=SOON)
    run(account)

    new_start = SOON + timedelta(days=1)
    fake.edit_remote(CAL, note.public_id.hex, summary="Dentist!", **timed(new_start.isoformat(), new_start.isoformat()))
    writes = len(fake.writes)
    result = run(account)

    assert result.updated == 1
    note.refresh_from_db()
    assert note.title == "Dentist!"
    assert note.starts_at == new_start
    assert len(fake.writes) == writes
    assert run(account).patched == 0


def test_conflict_goes_to_the_later_edit(account, fake, note_factory):
    note = note_factory(title="Original", body_format=ContentFormat.PLAIN, starts_at=SOON)
    run(account)

    # Google edited later than the note -> Google wins.
    note.refresh_from_db()
    note.title = "Local"
    note.save()
    fake.edit_remote(CAL, note.public_id.hex, summary="Remote")
    run(account)
    note.refresh_from_db()
    assert note.title == "Remote"
    assert fake.get(CAL, note.public_id.hex)["summary"] == "Remote"

    # Note edited later than Google -> the note wins.
    fake.clock_offset = timedelta(hours=-1)
    fake.edit_remote(CAL, note.public_id.hex, summary="Remote again")
    note.refresh_from_db()
    note.title = "Local again"
    note.save()
    run(account)
    note.refresh_from_db()
    assert note.title == "Local again"
    assert fake.get(CAL, note.public_id.hex)["summary"] == "Local again"


def test_rich_text_body_is_not_overwritten_from_google(account, fake, note_factory):
    note = note_factory(title="Recipe", body_format=ContentFormat.HTML, body="<p>Flour</p>", starts_at=SOON)
    run(account)
    fake.edit_remote(CAL, note.public_id.hex, description="changed in Google")

    run(account)
    note.refresh_from_db()
    assert note.body == "<p>Flour</p>"
    assert fake.get(CAL, note.public_id.hex)["description"] == "Flour"


def test_trash_restore_and_purge_follow_to_google(account, fake, note_factory):
    note = note_factory(title="Gym", body_format=ContentFormat.PLAIN, starts_at=SOON)
    run(account)
    event_id = note.public_id.hex

    note.soft_delete()
    assert run(account).deleted == 1
    assert fake.get(CAL, event_id)["status"] == "cancelled"
    assert not GoogleEventLink.objects.exists()

    note.restore()
    run(account)  # insert -> 409 (id taken) -> the cancelled event is revived
    assert fake.get(CAL, event_id)["status"] == "confirmed"
    assert GoogleEventLink.objects.filter(note=note).count() == 1

    Note.objects.filter(pk=note.pk).delete()  # purge
    assert run(account).deleted == 1
    assert fake.get(CAL, event_id)["status"] == "cancelled"
    assert not GoogleEventLink.objects.exists()


def test_deleting_in_google_trashes_the_note(account, fake):
    event = fake.add_remote(CAL, {"summary": "Party", **all_day(SOON.date().isoformat(), (SOON.date() + timedelta(days=1)).isoformat())})
    run(account)
    note = Note.objects.get(title="Party")
    assert note.all_day

    fake.delete_remote(CAL, event["id"])
    assert run(account).trashed == 1
    note.refresh_from_db()
    assert note.deleted_at is not None


def test_documents_are_read_only_in_google(account, fake, note_factory):
    document = note_factory(title="Fridge", kind=NoteKind.WARRANTY, expires_at=SOON)
    run(account)
    event_id = document.public_id.hex
    assert fake.get(CAL, event_id)["start"] == {"date": timezone.localtime(SOON, account_tz(account)).date().isoformat()}

    fake.edit_remote(CAL, event_id, summary="Hacked")
    run(account)
    document.refresh_from_db()
    assert document.title == "Fridge"
    assert fake.get(CAL, event_id)["summary"] == "Fridge"

    fake.delete_remote(CAL, event_id)
    run(account)
    assert fake.get(CAL, event_id)["status"] == "confirmed"

    account.push_documents = False
    account.push_pending = True  # what the settings page / admin set along with it
    account.save()
    run(account)
    assert fake.get(CAL, event_id)["status"] == "cancelled"


def account_tz(account):
    return sync.owner_zone_for(account)


def test_old_events_and_single_occurrence_exceptions_are_not_imported(account, fake):
    past = timezone.now() - timedelta(days=400)
    fake.add_remote(CAL, {"summary": "Ancient", **timed(past.isoformat(), (past + timedelta(hours=1)).isoformat())})
    fake.add_remote(CAL, {"summary": "Moved occurrence", "recurringEventId": "series1", **timed(
        SOON.isoformat(), (SOON + timedelta(hours=1)).isoformat(),
    )})
    fake.add_remote(CAL, {"summary": "Birthday", "eventType": "birthday", **all_day("2026-12-01", "2026-12-02")})

    result = run(account)
    assert result.created == 0
    assert result.skipped == 2
    assert not Note.objects.filter(title__in=["Ancient", "Moved occurrence", "Birthday"]).exists()


def test_expired_sync_token_triggers_a_full_resync_without_duplicates(account, fake, note_factory):
    note_factory(title="Mine", body_format=ContentFormat.PLAIN, starts_at=SOON)
    fake.add_remote(CAL, {"summary": "Theirs", **timed(SOON.isoformat(), SOON.isoformat())})
    run(account)

    fake.expire_sync_tokens = True
    run(account)
    assert Note.objects.filter(title="Theirs").count() == 1
    assert len(fake.live(CAL)) == 2


def test_recurring_rule_round_trips_without_rewrites(account, fake, note_factory):
    note = note_factory(title="Standup", body_format=ContentFormat.PLAIN, starts_at=SOON,
                        recurrence="FREQ=WEEKLY;UNTIL=20271231T235959")
    run(account)
    assert fake.get(CAL, note.public_id.hex)["recurrence"] == ["RRULE:FREQ=WEEKLY;UNTIL=20271231T215959Z"]
    writes = len(fake.writes)
    run(account, reconcile=True)
    assert len(fake.writes) == writes


def test_switching_calendars(account, fake, note_factory):
    mine = note_factory(title="Mine", body_format=ContentFormat.PLAIN, starts_at=SOON)
    fake.add_remote(CAL, {"summary": "Imported", **timed(SOON.isoformat(), SOON.isoformat())})
    run(account)
    imported = Note.objects.get(title="Imported")

    sync.switch_calendar(account, "work@group.calendar.google.com", "Work")
    run(account)

    assert fake.get(CAL, mine.public_id.hex)["status"] == "cancelled"
    assert fake.get("work@group.calendar.google.com", mine.public_id.hex)["status"] == "confirmed"
    assert GoogleEventLink.objects.get(note=imported).state == GoogleEventLink.State.DETACHED
    assert [e["summary"] for e in fake.live("work@group.calendar.google.com")] == ["Mine"]


def test_revoked_grant_asks_to_reconnect(account, fake, user):
    fake.fail_with = GoogleAuthError("invalid_grant", 400)
    account.refresh_from_db()
    sync.sync_account(account)

    account.refresh_from_db()
    assert account.status == GoogleCalendarAccount.Status.NEEDS_RECONNECT
    assert account.refresh_token_enc == ""
    assert Notification.objects.filter(recipient=user).count() == 1
    assert sync.sync_account(account) is None  # not retried until reconnected


def test_server_errors_back_off(account, fake):
    fake.fail_with = GoogleServerError("boom", 503)
    account.refresh_from_db()
    sync.sync_account(account)
    account.refresh_from_db()
    assert account.consecutive_failures == 1
    assert account.retry_after > timezone.now()
    assert account.status == GoogleCalendarAccount.Status.ACTIVE


def test_a_running_sync_holds_the_lock(account, fake):
    cache.add(sync._lock_key(account), 1)
    assert sync.sync_account(account) is None


@override_config(GOOGLE_CALENDAR_MAX_WRITES_PER_RUN=2)
def test_writes_per_run_are_capped(account, fake, note_factory):
    for index in range(3):
        note_factory(title=f"N{index}", body_format=ContentFormat.PLAIN, starts_at=SOON + timedelta(hours=index))
    assert run(account).inserted == 2
    assert run(account).inserted == 1


def test_saving_a_note_queues_a_push_but_pulled_writes_dont(account, fake, settings, note_factory, django_capture_on_commit_callbacks):
    settings.GOOGLE_OAUTH_CLIENT_ID = "client"
    settings.GOOGLE_OAUTH_CLIENT_SECRET = "secret"
    settings.GOOGLE_CALENDAR_ENQUEUE_ON_SAVE = True
    with patch("apps.events.signals.push_notes_to_google.apply_async") as apply_async:
        with django_capture_on_commit_callbacks(execute=True):
            note = note_factory(title="Queued", body_format=ContentFormat.PLAIN, starts_at=SOON)
        assert apply_async.call_args.args[0] == ([note.pk],)

        apply_async.reset_mock()
        fake.add_remote(CAL, {"summary": "Pulled", **timed(SOON.isoformat(), SOON.isoformat())})
        with django_capture_on_commit_callbacks(execute=True):
            run(account)
        apply_async.assert_not_called()


def test_push_notes_pushes_only_the_given_notes(account, fake, note_factory):
    first = note_factory(title="First", body_format=ContentFormat.PLAIN, starts_at=SOON)
    note_factory(title="Second", body_format=ContentFormat.PLAIN, starts_at=SOON)
    account.refresh_from_db()
    result = sync.push_notes(account, [first.pk])
    assert result.inserted == 1
    assert [e["summary"] for e in fake.live(CAL)] == ["First"]


# --- sync direction ---


def _set_direction(account, direction):
    account.sync_direction = direction
    account.save(update_fields=["sync_direction"])


def test_from_google_imports_but_never_writes_to_google(account, fake, note_factory):
    _set_direction(account, GoogleCalendarAccount.SyncDirection.FROM_GOOGLE)
    note_factory(title="Local only", body_format=ContentFormat.PLAIN, starts_at=SOON)
    event = fake.add_remote(CAL, {"summary": "Concert", **timed(SOON.isoformat(), SOON.isoformat())})

    result = run(account)
    assert (result.created, result.inserted) == (1, 0)
    imported = Note.objects.get(title="Concert")

    # A local edit stays local and doesn't block the next change from Google.
    imported.title = "Concert (local)"
    imported.save()
    fake.clock_offset = timedelta(hours=-1)  # even an older Google edit wins
    fake.edit_remote(CAL, event["id"], summary="Concert (moved)")
    run(account)
    imported.refresh_from_db()
    assert imported.title == "Concert (moved)"
    assert fake.writes == []
    assert sync.push_notes(account, [imported.pk]) is None


def test_to_google_keeps_google_a_read_only_copy(account, fake, note_factory):
    _set_direction(account, GoogleCalendarAccount.SyncDirection.TO_GOOGLE)
    note = note_factory(title="Dentist", body_format=ContentFormat.PLAIN, starts_at=SOON)
    fake.add_remote(CAL, {"summary": "Made in Google", **timed(SOON.isoformat(), SOON.isoformat())})

    result = run(account)
    assert (result.inserted, result.created, result.skipped) == (1, 0, 1)
    assert not Note.objects.filter(title="Made in Google").exists()

    # An edit made in Google is put back.
    fake.edit_remote(CAL, note.public_id.hex, summary="Changed in Google")
    run(account)
    note.refresh_from_db()
    assert note.title == "Dentist"
    assert fake.get(CAL, note.public_id.hex)["summary"] == "Dentist"

    # Deleted in Google: the note stays, the event comes back.
    fake.delete_remote(CAL, note.public_id.hex)
    result = run(account)
    note.refresh_from_db()
    assert note.deleted_at is None and result.trashed == 0
    run(account)
    assert fake.get(CAL, note.public_id.hex)["status"] == "confirmed"


def test_switching_to_both_ways_imports_what_was_skipped(account, fake, client, user, settings):
    _set_direction(account, GoogleCalendarAccount.SyncDirection.TO_GOOGLE)
    fake.add_remote(CAL, {"summary": "Made in Google", **timed(SOON.isoformat(), SOON.isoformat())})
    run(account)
    assert not Note.objects.filter(title="Made in Google").exists()

    settings.GOOGLE_CALENDAR_SYNC_INLINE = True
    client.force_login(user)
    client.post(reverse("events:google_settings"), {
        "calendar_id": CAL, "sync_direction": GoogleCalendarAccount.SyncDirection.BOTH,
        "sync_enabled": "on", "push_documents": "on",
    })
    account.refresh_from_db()
    assert account.sync_direction == GoogleCalendarAccount.SyncDirection.BOTH
    assert Note.objects.filter(title="Made in Google").exists()  # the full resync imported it


# --- cost of a run at scale ---


def test_an_idle_run_is_one_google_call_and_a_few_queries(account, fake, note_factory, django_assert_max_num_queries):
    for index in range(20):
        note_factory(title=f"N{index}", body_format=ContentFormat.PLAIN, starts_at=SOON + timedelta(hours=index))
    run(account)
    account.refresh_from_db()
    assert not account.push_pending

    calls = fake.calls
    # Independent of how many notes the user has - this run even gets the
    # echo of the 20 inserts above back from Google (links loaded per page).
    with django_assert_max_num_queries(5):
        result = sync.sync_account(account)
    assert not result.changed and not result.errors
    assert fake.calls == calls + 1


def test_local_changes_flag_a_push_and_unflagged_ones_wait_for_the_reconcile(account, fake, note_factory):
    note = note_factory(title="Dentist", body_format=ContentFormat.PLAIN, starts_at=SOON)
    run(account)

    note.refresh_from_db()
    note.title = "Dentist (moved)"
    note.save()  # signals.py flags the account
    account.refresh_from_db()
    assert account.push_pending
    assert run(account).patched == 1
    account.refresh_from_db()
    assert not account.push_pending

    with sync.suppress_push():  # a write the signals don't flag (like an admin bulk update)
        note_factory(title="Unflagged", body_format=ContentFormat.PLAIN, starts_at=SOON)
    assert run(account).inserted == 0
    assert run(account, reconcile=True).inserted == 1


def test_purging_a_note_flags_a_push(account, fake, note_factory):
    note = note_factory(title="Gym", body_format=ContentFormat.PLAIN, starts_at=SOON)
    run(account)
    Note.objects.filter(pk=note.pk).delete()
    account.refresh_from_db()
    assert account.push_pending
    assert run(account).deleted == 1


def test_the_next_runs_are_scheduled_with_jitter(account, fake):
    run(account)
    account.refresh_from_db()
    now = timezone.now()
    assert timedelta(minutes=7) < account.next_sync_at - now < timedelta(minutes=13)  # 10 min +/-25%
    assert timedelta(hours=17) < account.next_reconcile_at - now < timedelta(hours=31)  # a day +/-25%
