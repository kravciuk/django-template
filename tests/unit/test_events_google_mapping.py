from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from apps.common.enums import ContentFormat
from apps.content.enums import NoteKind
from apps.events.google import mapping
from apps.events.recurrence import all_day_moment
from libs.html import html_to_text

pytestmark = pytest.mark.django_db

VILNIUS = ZoneInfo("Europe/Vilnius")


def _round_trip(note):
    """What Google would hand back for the event built from `note`."""
    body = mapping.new_event_body(note, VILNIUS)
    body.setdefault("reminders", {"useDefault": True})
    return mapping.project_event(body, VILNIUS)


@pytest.mark.parametrize("fields", [
    {"starts_at": datetime(2026, 10, 5, 7, 30, tzinfo=UTC), "expires_at": datetime(2026, 10, 5, 9, 0, tzinfo=UTC)},
    {"starts_at": datetime(2026, 10, 5, 7, 30, tzinfo=UTC)},
    {"expires_at": datetime(2026, 10, 5, 7, 30, tzinfo=UTC)},
    {"all_day": True, "starts_at": all_day_moment(datetime(2026, 10, 5).date()),
     "expires_at": all_day_moment(datetime(2026, 10, 7).date())},
    {"all_day": True, "starts_at": all_day_moment(datetime(2026, 10, 5).date())},
    {"starts_at": datetime(2026, 10, 5, 7, 30, tzinfo=UTC), "recurrence": "FREQ=WEEKLY;UNTIL=20261231T235959"},
    {"all_day": True, "starts_at": all_day_moment(datetime(2026, 10, 5).date()),
     "recurrence": "FREQ=YEARLY;INTERVAL=2;UNTIL=20301005T235959"},
    {"starts_at": datetime(2026, 10, 5, 7, 30, tzinfo=UTC), "remind_minutes_before": 15, "color": "#dc2127"},
    {"starts_at": datetime(2026, 10, 5, 7, 30, tzinfo=UTC), "remind_minutes_before": 60 * 24 * 60},
    {"starts_at": datetime(2026, 10, 5, 7, 30, tzinfo=UTC), "body_format": ContentFormat.HTML,
     "body": "<p>One <b>two</b></p><p>three &amp; four</p>"},
])
def test_note_projection_survives_a_google_round_trip(note_factory, fields):
    fields.setdefault("body_format", ContentFormat.PLAIN)
    note = note_factory(title="Trip", **fields)
    assert _round_trip(note) == mapping.project_note(note, VILNIUS)


def test_document_projection_survives_a_google_round_trip(note_factory):
    note = note_factory(title="Fridge warranty", kind=NoteKind.WARRANTY, expires_at=datetime(2027, 3, 1, 21, 30, tzinfo=UTC))
    body = mapping.new_event_body(note, VILNIUS)
    assert body["transparency"] == "transparent"
    assert body["extendedProperties"]["private"]["kind"] == "document"
    assert _round_trip(note) == mapping.project_note(note, VILNIUS)


def test_document_is_an_all_day_event_on_the_local_expiry_date(note_factory):
    note = note_factory(title="Contract", kind=NoteKind.CONTRACT, expires_at=datetime(2027, 3, 1, 22, 30, tzinfo=UTC))
    body = mapping.new_event_body(note, VILNIUS)
    assert body["start"] == {"date": "2027-03-02"}  # 00:30 local
    assert body["end"] == {"date": "2027-03-03"}


def test_timed_until_is_sent_as_utc_and_all_day_until_as_a_date(note_factory):
    timed = note_factory(starts_at=datetime(2026, 10, 5, 7, 30, tzinfo=UTC), recurrence="FREQ=WEEKLY;UNTIL=20261231T235959")
    assert mapping.event_body(timed, VILNIUS)["recurrence"] == ["RRULE:FREQ=WEEKLY;UNTIL=20261231T215959Z"]

    whole_day = note_factory(all_day=True, starts_at=all_day_moment(datetime(2026, 10, 5).date()),
                             recurrence="FREQ=DAILY;UNTIL=20261010T235959")
    assert mapping.event_body(whole_day, VILNIUS)["recurrence"] == ["RRULE:FREQ=DAILY;UNTIL=20261010"]


def test_google_until_is_stored_as_local_time():
    canonical = mapping.canonical_rule("FREQ=WEEKLY;UNTIL=20260701T205959Z", VILNIUS, all_day=False, from_google=True)
    assert mapping.stored_rule(canonical, VILNIUS, all_day=False) == "FREQ=WEEKLY;UNTIL=20260701T235959"  # EEST, +3


def test_other_recurrence_lines_are_ignored():
    event = {"start": {"date": "2026-10-05"}, "end": {"date": "2026-10-06"},
             "recurrence": ["EXDATE;VALUE=DATE:20261012", "RRULE:FREQ=WEEKLY"]}
    assert mapping.project_event(event, VILNIUS)["recurrence"] == "FREQ=WEEKLY"


def test_reminders_and_colors():
    assert mapping._event_reminder({"reminders": {"useDefault": True}}) is None
    assert mapping._event_reminder({"reminders": {"useDefault": False, "overrides": []}}) is None
    assert mapping._event_reminder({"reminders": {"useDefault": False, "overrides": [
        {"method": "email", "minutes": 5}, {"method": "popup", "minutes": 30}, {"method": "popup", "minutes": 10},
    ]}}) == 10
    assert mapping.nearest_color_id("") is None
    assert mapping.nearest_color_id("#dc2127") == "11"
    assert mapping.nearest_color_id("#3a3f44") in mapping.GOOGLE_EVENT_COLORS


def test_patch_bodies_clear_the_other_time_variant(note_factory):
    note = note_factory(all_day=True, starts_at=all_day_moment(datetime(2026, 10, 5).date()))
    body = mapping.event_body(note, VILNIUS, keys=["when", "reminder", "color_id"], for_patch=True)
    assert body["start"] == {"date": "2026-10-05", "dateTime": None, "timeZone": None}
    assert body["reminders"] == {"useDefault": True, "overrides": None}
    assert body["colorId"] is None


def test_apply_projection_keeps_a_deadline_only_note_in_shape(note_factory):
    note = note_factory(expires_at=datetime(2026, 10, 5, 7, 0, tzinfo=UTC))
    when = {"all_day": False, "start": "2026-10-06T07:00:00Z", "end": "2026-10-06T07:00:00Z"}
    assert mapping.apply_projection(note, {"when": when}, VILNIUS)
    assert note.starts_at is None
    assert note.expires_at == datetime(2026, 10, 6, 7, 0, tzinfo=UTC)


def test_html_to_text():
    assert html_to_text("<p>Hello <b>world</b></p><p>a &lt; b<br>next</p>") == "Hello world\na < b\nnext"
    assert html_to_text("") == ""
