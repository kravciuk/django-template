from datetime import UTC, date, datetime, timedelta

import pytest
from constance.test import override_config
from django.urls import reverse
from django.utils import timezone

from apps.common.enums import ContentFormat, Visibility
from apps.content.enums import NoteKind
from apps.content.forms import NoteForm
from apps.content.models import Note
from apps.events.recurrence import all_day_moment
from apps.events.services import (
    DARK_TEXT,
    LIGHT_TEXT,
    calendar_entries,
    calendar_tags,
    get_events_hub,
    readable_text_color,
)

pytestmark = pytest.mark.django_db

WINDOW_START = datetime(2026, 10, 1, tzinfo=UTC)
WINDOW_END = datetime(2026, 11, 1, tzinfo=UTC)


def _ids(entries):
    return {entry["extendedProps"]["public_id"] for entry in entries}


def _feed(client, **params):
    params.setdefault("start", "2026-10-01T00:00:00Z")
    params.setdefault("end", "2026-11-01T00:00:00Z")
    return client.get(reverse("events:feed"), params)


# --- hub node ---

def test_events_hub_is_created_once_as_unlisted_node(user):
    hub = get_events_hub(user)
    assert hub.kind == NoteKind.NODE
    assert hub.visibility == Visibility.UNLISTED
    assert get_events_hub(user) == hub


def test_events_hub_is_recreated_after_trash(user):
    hub = get_events_hub(user)
    hub.soft_delete()
    assert get_events_hub(user) != hub


def test_events_hub_is_per_owner(user, other_user):
    assert get_events_hub(user) != get_events_hub(other_user)


# --- page ---

def test_calendar_requires_login(client):
    response = client.get(reverse("events:home"))
    assert response.status_code == 302


def test_calendar_page_renders(client, user):
    client.force_login(user)
    response = client.get(reverse("events:home"))
    assert response.status_code == 200
    assert b"events-calendar" in response.content


# --- quick-note API ---

def test_create_quick_note_under_hub(client, user):
    client.force_login(user)
    response = client.post(reverse("events:note-list"), {
        "title": "Dentist", "body": "Bring the card", "starts_at": "2026-10-05T10:00:00+00:00",
        "ends_at": "2026-10-05T11:00:00+00:00", "all_day": False,
    }, content_type="application/json")

    assert response.status_code == 201, response.content
    note = Note.objects.get(public_id=response.json()["public_id"])
    assert note.kind == NoteKind.EVENT
    assert note.visibility == Visibility.PRIVATE
    assert note.body_format == ContentFormat.PLAIN
    assert note.owner == user
    assert not note.is_draft
    assert Note.objects.get_parent(note) == get_events_hub(user)


def test_create_as_draft_for_full_form(client, user):
    client.force_login(user)
    response = client.post(reverse("events:note-list"), {
        "title": "Later", "starts_at": "2026-10-05", "ends_at": "2026-10-06", "all_day": True, "is_draft": True,
    }, content_type="application/json")
    assert response.status_code == 201
    note = Note.objects.get(public_id=response.json()["public_id"])
    assert note.is_draft
    assert response.json()["edit_url"] == reverse("content:note_edit", args=[note.public_id])


def test_all_day_end_is_exclusive_on_the_wire_and_inclusive_in_db(client, user):
    client.force_login(user)
    response = client.post(reverse("events:note-list"), {
        "title": "Trip", "starts_at": "2026-10-05", "ends_at": "2026-10-08", "all_day": True,
    }, content_type="application/json")
    note = Note.objects.get(public_id=response.json()["public_id"])
    assert note.starts_at == all_day_moment(date(2026, 10, 5))
    assert note.expires_at == all_day_moment(date(2026, 10, 7))
    assert response.json()["starts_at"] == "2026-10-05"
    assert response.json()["ends_at"] == "2026-10-08"


@pytest.mark.parametrize("payload", [
    {"color": "red"},
    {"recurrence": "FREQ=NOPE"},
    {"starts_at": "2026-10-05T10:00:00Z", "ends_at": "2026-10-05T09:00:00Z"},
    {"starts_at": None, "ends_at": None},
])
def test_create_rejects_invalid_input(client, user, payload):
    client.force_login(user)
    data = {"title": "Bad", "starts_at": "2026-10-05T10:00:00Z", **payload}
    response = client.post(reverse("events:note-list"), data, content_type="application/json")
    assert response.status_code == 400


def test_patch_moves_dates_only(client, user, note_factory):
    note = note_factory(title="Call", kind=NoteKind.EVENT, starts_at=datetime(2026, 10, 5, 10, tzinfo=UTC))
    client.force_login(user)
    response = client.patch(
        reverse("events:note-detail", args=[note.public_id]),
        {"starts_at": "2026-10-07T12:00:00Z", "all_day": False},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    note.refresh_from_db()
    assert note.starts_at == datetime(2026, 10, 7, 12, tzinfo=UTC)
    assert note.title == "Call"


def test_patch_ignores_body_of_rich_text_note(client, user, note_factory):
    note = note_factory(title="Rich", body="<p>keep</p>", body_format=ContentFormat.HTML,
                        starts_at=datetime(2026, 10, 5, tzinfo=UTC))
    client.force_login(user)
    client.patch(reverse("events:note-detail", args=[note.public_id]), {"body": "plain"},
                 content_type="application/json")
    note.refresh_from_db()
    assert note.body == "<p>keep</p>"


def test_documents_and_other_users_notes_are_out_of_reach(client, user, other_user, note_factory):
    document = note_factory(title="Warranty", kind=NoteKind.WARRANTY, expires_at=datetime(2026, 10, 5, tzinfo=UTC))
    foreign = note_factory(title="Not mine", owner=other_user, starts_at=datetime(2026, 10, 5, tzinfo=UTC))
    client.force_login(user)
    for note in (document, foreign):
        response = client.patch(reverse("events:note-detail", args=[note.public_id]), {"title": "x"},
                                content_type="application/json")
        assert response.status_code == 404


def test_delete_soft_deletes(client, user, note_factory):
    note = note_factory(title="Gone", kind=NoteKind.EVENT, starts_at=datetime(2026, 10, 5, tzinfo=UTC))
    client.force_login(user)
    response = client.delete(reverse("events:note-detail", args=[note.public_id]))
    assert response.status_code == 204
    note.refresh_from_db()
    assert note.is_trashed


# --- feed ---

def test_feed_includes_overlapping_notes_and_documents(user, note_factory):
    inside = note_factory(title="Inside", starts_at=datetime(2026, 10, 10, 9, tzinfo=UTC))
    spanning = note_factory(title="Spanning", starts_at=datetime(2026, 9, 20, tzinfo=UTC),
                            expires_at=datetime(2026, 10, 3, tzinfo=UTC))
    end_only = note_factory(title="Deadline", expires_at=datetime(2026, 10, 20, tzinfo=UTC))
    before = note_factory(title="Before", starts_at=datetime(2026, 8, 1, tzinfo=UTC))
    after = note_factory(title="After", starts_at=datetime(2026, 12, 1, tzinfo=UTC))
    document = note_factory(title="Contract", kind=NoteKind.CONTRACT, expires_at=datetime(2026, 10, 15, 12, tzinfo=UTC))

    entries = calendar_entries(user, WINDOW_START, WINDOW_END, tz=UTC)

    ids = _ids(entries)
    assert {str(inside.public_id), str(spanning.public_id), str(end_only.public_id), str(document.public_id)} <= ids
    assert str(before.public_id) not in ids
    assert str(after.public_id) not in ids
    document_entry = next(entry for entry in entries if entry["extendedProps"]["public_id"] == str(document.public_id))
    assert document_entry["allDay"] is True
    assert document_entry["editable"] is False
    assert document_entry["start"] == "2026-10-15"


def test_feed_excludes_drafts_trash_nodes_and_other_users(user, other_user, note_factory):
    draft = note_factory(title="Draft", is_draft=True, starts_at=datetime(2026, 10, 10, tzinfo=UTC))
    trashed = note_factory(title="Trashed", starts_at=datetime(2026, 10, 10, tzinfo=UTC))
    trashed.soft_delete()
    node = note_factory(title="Node", kind=NoteKind.NODE, starts_at=datetime(2026, 10, 10, tzinfo=UTC))
    foreign = note_factory(title="Foreign", owner=other_user, starts_at=datetime(2026, 10, 10, tzinfo=UTC))

    ids = _ids(calendar_entries(user, WINDOW_START, WINDOW_END, tz=UTC))

    assert not ids & {str(n.public_id) for n in (draft, trashed, node, foreign)}


def test_feed_expands_recurring_notes_as_non_editable_occurrences(user, note_factory):
    note = note_factory(title="Gym", starts_at=datetime(2026, 9, 1, 18, tzinfo=UTC), recurrence="FREQ=WEEKLY")
    entries = [e for e in calendar_entries(user, WINDOW_START, WINDOW_END, tz=UTC)
               if e["extendedProps"]["public_id"] == str(note.public_id)]
    assert len(entries) == 4
    assert all(entry["editable"] is False and entry["extendedProps"]["recurring"] for entry in entries)
    assert len({entry["id"] for entry in entries}) == 4


def test_feed_filters_by_source_and_tag(client, user, note_factory):
    tagged = note_factory(title="Tagged", starts_at=datetime(2026, 10, 10, tzinfo=UTC))
    tagged.tags.add("health")
    note_factory(title="Plain", starts_at=datetime(2026, 10, 11, tzinfo=UTC))
    note_factory(title="Doc", kind=NoteKind.WARRANTY, expires_at=datetime(2026, 10, 12, tzinfo=UTC))
    client.force_login(user)

    only_docs = _feed(client, sources="document").json()
    assert {entry["extendedProps"]["source"] for entry in only_docs} == {"document"}

    only_tag = _feed(client, tags="health").json()
    assert [entry["title"] for entry in only_tag] == ["Tagged"]

    assert calendar_tags(user) == ["health"]
    assert client.get(reverse("events:tags")).json() == ["health"]


def test_feed_rejects_bad_range(client, user):
    client.force_login(user)
    assert _feed(client, start="nope").status_code == 400
    assert _feed(client, start="2026-11-01", end="2026-10-01").status_code == 400


def test_feed_accepts_naive_bounds_in_the_users_zone(client, user, note_factory):
    user.timezone = "Europe/Vilnius"
    user.save()
    note_factory(title="Edge", starts_at=datetime(2026, 9, 30, 22, 30, tzinfo=UTC))  # 01:30 Oct 1 in Vilnius
    client.force_login(user)
    entries = _feed(client, start="2026-10-01T00:00:00", end="2026-10-02T00:00:00").json()
    assert [entry["title"] for entry in entries] == ["Edge"]
    assert entries[0]["start"].endswith("+03:00")


# --- colors ---

@override_config(EVENTS_NOTE_COLOR="#111111", EVENTS_DOCUMENT_COLOR="#222222")
def test_entry_colors_default_by_source_and_note_override_wins(user, note_factory):
    note_factory(title="Gray", starts_at=datetime(2026, 10, 10, tzinfo=UTC))
    note_factory(title="Custom", starts_at=datetime(2026, 10, 11, tzinfo=UTC), color="#ffeeaa")
    note_factory(title="Doc", kind=NoteKind.PURCHASE, expires_at=datetime(2026, 10, 12, tzinfo=UTC))

    colors = {e["title"]: e["backgroundColor"] for e in calendar_entries(user, WINDOW_START, WINDOW_END, tz=UTC)}

    assert colors == {"Gray": "#111111", "Custom": "#ffeeaa", "Doc": "#222222"}


def test_readable_text_color_flips_on_light_backgrounds():
    assert readable_text_color("#3a3f44") == LIGHT_TEXT
    assert readable_text_color("#ffeeaa") == DARK_TEXT


# --- notes UI integration ---

def test_home_feed_excludes_quick_notes(client, user, note_factory):
    note_factory(title="Visible", visibility=Visibility.PUBLIC)
    note_factory(title="Quick", kind=NoteKind.EVENT, visibility=Visibility.PUBLIC)
    client.force_login(user)
    response = client.get(reverse("content:home"))
    titles = [entry["note"].title for entry in response.context["entries"]]
    assert "Visible" in titles
    assert "Quick" not in titles


def test_home_shows_upcoming_events_widget(client, user, note_factory):
    # PRIVATE keeps them out of the "Recent notes" feed on the same page.
    note_factory(title="Soon", visibility=Visibility.PRIVATE, starts_at=timezone.now() + timedelta(days=2))
    note_factory(title="Far", visibility=Visibility.PRIVATE, starts_at=timezone.now() + timedelta(days=30))
    client.force_login(user)
    body = client.get(reverse("content:home")).content.decode()
    assert "Soon" in body
    assert "Far" not in body


def test_note_form_rejects_end_before_start(user):
    form = NoteForm(data={
        "title": "x", "kind": NoteKind.NOTE, "body_format": ContentFormat.PLAIN, "body": "",
        "visibility": Visibility.PUBLIC, "starts_at": "2026-10-05T10:00", "expires_at": "2026-10-05T09:00",
        "use_default_color": "on",
    }, owner=user)
    assert not form.is_valid()
    assert "expires_at" in form.errors


def test_note_form_edits_quick_note_and_builds_recurrence(user, note_factory):
    note = note_factory(title="Quick", kind=NoteKind.EVENT, body_format=ContentFormat.PLAIN,
                        starts_at=datetime(2026, 10, 5, 10, tzinfo=UTC))
    form = NoteForm(instance=note, data={
        "title": "Quick", "kind": NoteKind.EVENT, "body_format": ContentFormat.PLAIN, "body": "",
        "visibility": Visibility.PRIVATE, "starts_at": "2026-10-05T10:00", "repeat": "YEARLY",
        "repeat_interval": "1", "color": "#123456", "remind_minutes_before": "60",
    }, owner=user)
    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.recurrence == "FREQ=YEARLY"
    assert saved.color == "#123456"
    assert saved.remind_minutes_before == 60


def test_note_form_all_day_keeps_the_date(user):
    form = NoteForm(data={
        "title": "x", "kind": NoteKind.NOTE, "body_format": ContentFormat.PLAIN, "body": "",
        "visibility": Visibility.PUBLIC, "starts_at": "2026-10-05T15:00", "all_day": "on",
        "use_default_color": "on",
    }, owner=user)
    assert form.is_valid(), form.errors
    assert form.cleaned_data["starts_at"] == all_day_moment(date(2026, 10, 5))
    assert form.cleaned_data["color"] == ""


def test_note_form_splits_calendar_fields_out(user):
    form = NoteForm(owner=user)
    calendar = [field.name for field in form.calendar_fields()]
    main = [field.name for field in form.main_fields()]
    assert calendar == [
        "starts_at", "expires_at", "all_day", "repeat", "repeat_interval", "repeat_until",
        "remind_minutes_before", "color", "use_default_color",
    ]
    assert not set(calendar) & set(main)
    assert "title" in main


def test_note_form_calendar_block_is_collapsed_for_a_note_off_the_calendar(client, user, note_factory):
    note = note_factory(owner=user)
    client.force_login(user)

    assert not NoteForm(owner=user).calendar_open
    response = client.get(reverse("content:note_edit", args=[note.public_id]))
    assert not response.context["form"].calendar_open
    assert 'class="accordion-collapse collapse"' in response.content.decode()


def test_note_form_calendar_block_is_open_for_a_note_on_the_calendar(client, user, note_factory):
    note = note_factory(owner=user, starts_at=datetime(2026, 10, 5, 10, tzinfo=UTC))
    client.force_login(user)

    response = client.get(reverse("content:note_edit", args=[note.public_id]))
    assert response.context["form"].calendar_open
    assert 'class="accordion-collapse collapse show"' in response.content.decode()


def test_note_form_calendar_block_opens_on_a_calendar_field_error(user):
    form = NoteForm(data={
        "title": "x", "kind": NoteKind.NOTE, "body_format": ContentFormat.PLAIN, "body": "",
        "visibility": Visibility.PUBLIC, "repeat": "DAILY", "use_default_color": "on",
    }, owner=user)
    assert not form.is_valid()
    assert "repeat" in form.errors
    assert form.calendar_open
