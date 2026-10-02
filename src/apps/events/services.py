"""Calendar data for /events/: the per-owner hidden hub node quick notes
live under, and the FullCalendar-shaped entries the feed, the home widget
and tests all share (calendar_entries)."""

from datetime import timedelta

from constance import config
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from taggit.models import Tag

from apps.common.enums import ContentFormat
from apps.content.enums import NoteKind
from apps.content.models import Note
from apps.documents.enums import DOCUMENT_KINDS

from .recurrence import all_day_date, event_bounds, occurrences

EVENTS_HUB_MARKER = "events"
EVENTS_HUB_TITLE = "Events"

SOURCE_NOTE = "note"
SOURCE_DOCUMENT = "document"
SOURCES = (SOURCE_NOTE, SOURCE_DOCUMENT)

DEFAULT_NOTE_COLOR = "#3a3f44"
DEFAULT_DOCUMENT_COLOR = "#5c3d2e"
LIGHT_TEXT = "#ffffff"
DARK_TEXT = "#1a1a1a"

# All-day values are stored as UTC midnight while the requested window is
# in the viewer's zone - widen the DB query by a day on each side so an
# edge-of-window all-day entry is never lost to that offset.
ALL_DAY_SLACK = timedelta(days=1)


def get_events_hub(owner):
    """The owner's hidden "Events" hub node (kind=NODE, which Note.save()
    forces to UNLISTED), created on first use. Found by a json_data marker
    rather than by title, so renaming it in the UI doesn't orphan it; a
    trashed hub is simply replaced by a new one."""
    hub = (
        Note.objects.alive()
        .filter(owner=owner, kind=NoteKind.NODE, json_data__system_hub=EVENTS_HUB_MARKER)
        .order_by("created_at")
        .first()
    )
    if hub is None:
        hub = Note.objects.add_root(instance=Note(
            owner=owner,
            title=EVENTS_HUB_TITLE,
            kind=NoteKind.NODE,
            json_data={"system_hub": EVENTS_HUB_MARKER},
        ))
    return hub


def is_document(note):
    return note.kind in DOCUMENT_KINDS


def default_color(source):
    if source == SOURCE_DOCUMENT:
        return getattr(config, "EVENTS_DOCUMENT_COLOR", DEFAULT_DOCUMENT_COLOR)
    return getattr(config, "EVENTS_NOTE_COLOR", DEFAULT_NOTE_COLOR)


def readable_text_color(background):
    """White or near-black, whichever reads better on `background` (#rrggbb),
    by WCAG relative luminance."""
    def channel(hex_pair):
        value = int(hex_pair, 16) / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    try:
        red, green, blue = (channel(background[i:i + 2]) for i in (1, 3, 5))
    except (TypeError, ValueError):
        return LIGHT_TEXT
    luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    return DARK_TEXT if luminance > 0.4 else LIGHT_TEXT


def entry_colors(note, source):
    background = note.color or default_color(source)
    return {
        "backgroundColor": background,
        "borderColor": background,
        "textColor": readable_text_color(background),
    }


def to_api_start(note, value):
    if value is None:
        return None
    if note.all_day:
        return all_day_date(value).isoformat()
    return timezone.localtime(value).isoformat()


def to_api_end(note, value):
    """Stored end -> wire end. All-day ends are stored inclusive but sent
    exclusive (the day after), the FullCalendar/Google convention."""
    if value is None:
        return None
    if note.all_day:
        return (all_day_date(value) + timedelta(days=1)).isoformat()
    return timezone.localtime(value).isoformat()


def from_api_end(day):
    """Wire end date (exclusive) -> the inclusive last day stored."""
    return day - timedelta(days=1)


def _overlap_q(start, end):
    """Non-recurring notes whose [start, end] placement overlaps the window
    (see recurrence.event_bounds for how start/end fall back)."""
    with_start = Q(starts_at__isnull=False, starts_at__lt=end) & (
        Q(expires_at__gte=start) | Q(expires_at__isnull=True, starts_at__gte=start)
    )
    end_only = Q(starts_at__isnull=True, expires_at__gte=start, expires_at__lt=end)
    return with_start | end_only


def _note_entry(note, start, end, *, recurring=False):
    entry_id = str(note.public_id)
    if recurring:
        entry_id = f"{entry_id}:{start.isoformat()}"
    return {
        "id": entry_id,
        "title": note.title,
        "start": to_api_start(note, start),
        "end": to_api_end(note, end),
        "allDay": note.all_day,
        # Recurring occurrences are edited as a whole series through the
        # modal - dragging one occurrence would need per-occurrence
        # exceptions, which aren't supported (docs/future/calendar-next-steps.md).
        "editable": not recurring,
        "classNames": ["ev-note", f"ev-kind-{note.kind}"],
        **entry_colors(note, SOURCE_NOTE),
        "extendedProps": {
            "source": SOURCE_NOTE,
            "public_id": str(note.public_id),
            "kind": note.kind,
            "body": note.body if note.body_format == ContentFormat.PLAIN else "",
            "color": note.color,
            "recurring": recurring,
            "recurrence": note.recurrence,
            "remind_minutes_before": note.remind_minutes_before,
            "detail_url": reverse("content:note_detail", args=[note.public_id]),
            "edit_url": reverse("content:note_edit", args=[note.public_id]),
        },
    }


def _document_entry(note, tz):
    day = timezone.localtime(note.expires_at, tz).date()
    return {
        "id": str(note.public_id),
        "title": note.title,
        "start": day.isoformat(),
        "end": (day + timedelta(days=1)).isoformat(),
        "allDay": True,
        "editable": False,
        "classNames": ["ev-document", f"ev-kind-{note.kind}"],
        **entry_colors(note, SOURCE_DOCUMENT),
        "extendedProps": {
            "source": SOURCE_DOCUMENT,
            "public_id": str(note.public_id),
            "kind": note.kind,
            "kind_label": note.get_kind_display(),
            "expires_at": timezone.localtime(note.expires_at, tz).isoformat(),
            "detail_url": reverse("documents:detail", args=[note.public_id]),
            "edit_url": reverse("documents:edit", args=[note.public_id]),
        },
    }


def calendar_entries(owner, start, end, *, sources=None, tags=None, tz=None):
    """FullCalendar event dicts for everything of `owner`'s that falls in
    [start, end): calendar-placed notes (recurring ones expanded) and
    document deadlines. Drafts, trashed rows and hub nodes never show."""
    tz = tz or timezone.get_current_timezone()
    sources = set(sources or SOURCES)
    base = Note.objects.alive().filter(owner=owner, is_draft=False).exclude(kind=NoteKind.NODE)
    if tags:
        base = base.filter(tags__name__in=tags).distinct()
    wide_start, wide_end = start - ALL_DAY_SLACK, end + ALL_DAY_SLACK

    entries = []
    if SOURCE_NOTE in sources:
        notes = base.exclude(kind__in=DOCUMENT_KINDS)
        for note in notes.filter(recurrence="").filter(_overlap_q(wide_start, wide_end)):
            note_start, note_end = event_bounds(note)
            entries.append(_note_entry(note, note_start, note_end))
        recurring = notes.exclude(recurrence="").filter(
            Q(starts_at__lt=wide_end) | Q(starts_at__isnull=True, expires_at__lt=wide_end)
        )
        for note in recurring:
            for occurrence_start, occurrence_end in occurrences(note, start, end, tz):
                entries.append(_note_entry(note, occurrence_start, occurrence_end, recurring=True))
    if SOURCE_DOCUMENT in sources:
        documents = base.filter(kind__in=DOCUMENT_KINDS, expires_at__gte=wide_start, expires_at__lt=wide_end)
        entries.extend(_document_entry(note, tz) for note in documents)
    return entries


def calendar_tags(owner):
    """Tag names used on any of `owner`'s calendar-placed notes or
    documents - the options for the calendar's tag filter."""
    placed = Note.objects.alive().filter(owner=owner, is_draft=False).filter(
        Q(starts_at__isnull=False) | Q(expires_at__isnull=False)
    )
    return list(
        Tag.objects.filter(
            taggit_taggeditem_items__content_type__app_label="content",
            taggit_taggeditem_items__object_id__in=placed.values("pk"),
        ).order_by("name").values_list("name", flat=True).distinct()
    )
