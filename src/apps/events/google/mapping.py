"""Note <-> Google Calendar event mapping.

Both sides are reduced to the same *projection* - a small JSON-safe dict of
the fields this sync owns, normalized so equal content compares equal:

    summary      title
    description  plain text
    when         {"all_day", "start", "end"} - dates ("YYYY-MM-DD", end
                 inclusive) for all-day, UTC "YYYY-MM-DDTHH:MM:SSZ" otherwise
    recurrence   canonical RRULE body ("" = none), UNTIL in UTC (timed) or
                 as a date (all-day)
    reminder     minutes before, or None (= Google's calendar default)
    color_id     Google event colorId, or None (= calendar default)

sync.py diffs projections against GoogleEventLink.snapshot (the last agreed
state) to find what changed on which side. Lossy fields are compared in
Google's terms (a note color as its nearest colorId, an HTML body as text),
so a value that can't round-trip exactly doesn't bounce back and forth.
"""
from datetime import UTC, datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext

from apps.common.enums import ContentFormat
from libs.html import html_to_text, looks_like_html

from ..recurrence import all_day_date, all_day_moment, event_bounds, validate_rrule
from ..reminders import reminder_offset
from ..services import from_api_end, is_document

PROJECTION_KEYS = ("summary", "description", "when", "recurrence", "reminder", "color_id")

TITLE_MAX_LENGTH = 255
# Google's upper limit for a reminder override (4 weeks).
MAX_REMINDER_MINUTES = 40320

# Google Calendar's fixed event palette (colors.get, "event").
GOOGLE_EVENT_COLORS = {
    "1": "#a4bdfc", "2": "#7ae7bf", "3": "#dbadff", "4": "#ff887c", "5": "#fbd75b", "6": "#ffb878",
    "7": "#46d6db", "8": "#e1e1e1", "9": "#5484ed", "10": "#51b749", "11": "#dc2127",
}

KIND_DOCUMENT = "document"
KIND_NOTE = "note"


# --- small helpers ---------------------------------------------------------


def _rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def nearest_color_id(color):
    """The Google event colorId closest (RGB distance) to #rrggbb, or None
    for "" (the calendar's own default)."""
    if not color:
        return None
    try:
        target = _rgb(color)
    except ValueError:
        return None
    return min(
        GOOGLE_EVENT_COLORS,
        key=lambda color_id: sum((a - b) ** 2 for a, b in zip(_rgb(GOOGLE_EVENT_COLORS[color_id]), target)),
    )


def _utc_string(value):
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_text(value):
    return "\n".join(line.rstrip() for line in (value or "").replace("\r\n", "\n").split("\n")).strip()


def note_description(note):
    """What a note's body looks like as a Google description (plain text)."""
    if note.body_format == ContentFormat.HTML:
        return html_to_text(note.body)
    return _normalize_text(note.body)


def remote_description(event):
    """Google's web UI stores formatted descriptions as HTML."""
    value = event.get("description") or ""
    return html_to_text(value) if looks_like_html(value) else _normalize_text(value)


def document_description(note):
    # Built in the default language: the projection must not depend on
    # which language happened to be active when a sync ran.
    with translation.override(settings.LANGUAGE_CODE):
        return gettext("%(kind)s expiry date. Managed by the notes site - edits made in Google are overwritten.") % {
            "kind": note.get_kind_display(),
        }


def note_kind(note):
    return KIND_DOCUMENT if is_document(note) else KIND_NOTE


# --- recurrence ------------------------------------------------------------


def _rule_parts(rule):
    parts = []
    for chunk in (rule or "").upper().split(";"):
        if "=" in chunk:
            key, value = chunk.split("=", 1)
            parts.append((key.strip(), value.strip()))
    return parts


def _join_rule(parts):
    ordered = sorted(parts, key=lambda part: (part[0] != "FREQ", part[0]))
    return ";".join(f"{key}={value}" for key, value in ordered)


def _parse_until(value, tz, *, all_day, assume_utc):
    """UNTIL value -> date (all-day) or aware datetime (timed)."""
    raw = value.rstrip("Z")
    is_utc = value.endswith("Z") and assume_utc
    if "T" in raw:
        moment = datetime.strptime(raw[:15], "%Y%m%dT%H%M%S")
    else:
        moment = datetime.combine(datetime.strptime(raw[:8], "%Y%m%d").date(), time(23, 59, 59))
    moment = moment.replace(tzinfo=UTC) if is_utc else moment.replace(tzinfo=tz)
    if all_day:
        return moment.astimezone(tz).date() if is_utc else moment.date()
    return moment


def canonical_rule(rule, tz, *, all_day, from_google):
    """Comparable form of an RRULE body. Our stored UNTIL is naive local
    time (any "Z" is ignored, as in recurrence.py); Google's is UTC ("Z") or
    floating in the event's zone. Timed rules end up with a UTC UNTIL,
    all-day ones with a date."""
    parts = []
    for key, value in _rule_parts(rule):
        if key == "UNTIL":
            until = _parse_until(value, tz, all_day=all_day, assume_utc=from_google)
            value = f"{until:%Y%m%d}" if all_day else until.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        parts.append((key, value))
    return _join_rule(parts)


def stored_rule(canonical, tz, *, all_day):
    """Canonical rule -> what Note.recurrence stores (naive local UNTIL,
    end-of-day for all-day like recurrence.build_rrule)."""
    parts = []
    for key, value in _rule_parts(canonical):
        if key == "UNTIL":
            if all_day:
                value = f"{value[:8]}T235959"
            else:
                until = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
                value = until.astimezone(tz).strftime("%Y%m%dT%H%M%S")
        parts.append((key, value))
    return _join_rule(parts)


def _google_rrule(event):
    for line in event.get("recurrence") or []:
        if line.upper().startswith("RRULE:"):
            return line[len("RRULE:"):]
    return ""


# --- projections -----------------------------------------------------------


def note_when(note, tz):
    """The note's placement as a projection "when", or None if it has no
    dates. Documents are an all-day entry on their expiry date in the
    owner's zone (same as the /events/ feed)."""
    if is_document(note):
        if note.expires_at is None:
            return None
        day = timezone.localtime(note.expires_at, tz).date().isoformat()
        return {"all_day": True, "start": day, "end": day}
    start, end = event_bounds(note)
    if start is None:
        return None
    if note.all_day:
        start_day = all_day_date(start)
        end_day = all_day_date(end) if end else start_day
        return {"all_day": True, "start": start_day.isoformat(), "end": max(start_day, end_day).isoformat()}
    end = end or start
    return {"all_day": False, "start": _utc_string(start), "end": _utc_string(max(start, end))}


def _note_reminder(note):
    offset = reminder_offset(note)
    if offset is None:
        return None
    return min(int(offset.total_seconds() // 60), MAX_REMINDER_MINUTES)


def project_note(note, tz):
    when = note_when(note, tz)
    if is_document(note):
        return {
            "summary": (note.title or "")[:TITLE_MAX_LENGTH],
            "description": document_description(note),
            "when": when,
            "recurrence": "",
            "reminder": _note_reminder(note),
            "color_id": None,
        }
    all_day = bool(when and when["all_day"])
    return {
        "summary": (note.title or "")[:TITLE_MAX_LENGTH],
        "description": note_description(note),
        "when": when,
        "recurrence": canonical_rule(note.recurrence, tz, all_day=all_day, from_google=False) if note.recurrence else "",
        "reminder": _note_reminder(note),
        "color_id": nearest_color_id(note.color),
    }


def event_when(event, tz):
    start, end = event.get("start") or {}, event.get("end") or {}
    if start.get("date"):
        start_day = parse_date(start["date"])
        end_day = from_api_end(parse_date(end["date"])) if end.get("date") else start_day
        return {"all_day": True, "start": start_day.isoformat(), "end": max(start_day, end_day).isoformat()}
    start_at = parse_datetime(start.get("dateTime", ""))
    end_at = parse_datetime(end.get("dateTime", "")) if end.get("dateTime") else None
    if start_at is None:
        return None
    end_at = end_at or start_at
    return {"all_day": False, "start": _utc_string(start_at), "end": _utc_string(max(start_at, end_at))}


def _event_reminder(event):
    reminders = event.get("reminders") or {}
    if reminders.get("useDefault", True):
        return None
    overrides = reminders.get("overrides") or []
    if not overrides:
        return None
    popups = [item["minutes"] for item in overrides if item.get("method") == "popup"]
    return min(popups or [item["minutes"] for item in overrides])


def project_event(event, tz):
    when = event_when(event, tz)
    rule = _google_rrule(event)
    all_day = bool(when and when["all_day"])
    return {
        "summary": (event.get("summary") or "")[:TITLE_MAX_LENGTH],
        "description": remote_description(event),
        "when": when,
        "recurrence": canonical_rule(rule, tz, all_day=all_day, from_google=True) if rule else "",
        "reminder": _event_reminder(event),
        "color_id": event.get("colorId") or None,
    }


# --- note -> Google --------------------------------------------------------


def _event_times(when, tz, *, for_patch):
    if when["all_day"]:
        end = (parse_date(when["end"]) + timedelta(days=1)).isoformat()
        start, end = {"date": when["start"]}, {"date": end}
        if for_patch:
            # PATCH merges objects - clear the timed variant explicitly.
            start.update(dateTime=None, timeZone=None)
            end.update(dateTime=None, timeZone=None)
        return start, end

    def timed(value):
        moment = parse_datetime(value).astimezone(tz)
        result = {"dateTime": moment.isoformat(), "timeZone": tz.key}
        if for_patch:
            result["date"] = None
        return result

    return timed(when["start"]), timed(when["end"])


def _event_reminders(minutes, *, for_patch):
    if minutes is None:
        return {"useDefault": True, "overrides": None} if for_patch else {"useDefault": True}
    return {"useDefault": False, "overrides": [{"method": "popup", "minutes": minutes}]}


def event_body(note, tz, *, keys=PROJECTION_KEYS, for_patch=False):
    """Google event resource fields for `note`, limited to the projection
    `keys` (a PATCH sends only what changed)."""
    projection = project_note(note, tz)
    body = {}
    if "summary" in keys:
        body["summary"] = projection["summary"]
    if "description" in keys:
        body["description"] = projection["description"]
    if "when" in keys:
        body["start"], body["end"] = _event_times(projection["when"], tz, for_patch=for_patch)
    if "recurrence" in keys:
        body["recurrence"] = [f"RRULE:{projection['recurrence']}"] if projection["recurrence"] else []
    if "reminder" in keys:
        body["reminders"] = _event_reminders(projection["reminder"], for_patch=for_patch)
    if "color_id" in keys:
        if projection["color_id"] or for_patch:
            body["colorId"] = projection["color_id"]
    return body


def new_event_body(note, tz):
    """Full resource for events.insert. The event id is derived from the
    note's public_id, so a retried insert can't create a duplicate."""
    body = event_body(note, tz)
    body["id"] = event_id_for(note)
    body["extendedProperties"] = {"private": {"note": str(note.public_id), "kind": note_kind(note)}}
    if is_document(note):
        body["transparency"] = "transparent"
    if settings.SITE_URL:
        url_name = "documents:detail" if is_document(note) else "content:note_detail"
        body["source"] = {"title": note.title[:TITLE_MAX_LENGTH], "url": settings.SITE_URL + reverse(url_name, args=[note.public_id])}
    return body


def event_id_for(note):
    # Google event ids allow base32hex characters (a-v, 0-9), 5-1024 long -
    # a UUID's lowercase hex fits.
    return note.public_id.hex


def linked_note_public_id(event):
    return ((event.get("extendedProperties") or {}).get("private") or {}).get("note")


# --- Google -> note --------------------------------------------------------


def apply_projection(note, values, tz):
    """Write projection `values` (a subset of PROJECTION_KEYS) onto `note`.
    Returns True if anything changed. Never touches the body of a rich-text
    note - sync.py doesn't pass "description" for those."""
    changed = False

    def assign(field, value):
        nonlocal changed
        if getattr(note, field) != value:
            setattr(note, field, value)
            changed = True

    if "summary" in values:
        assign("title", values["summary"] or gettext("(No title)"))
    if "description" in values:
        assign("body", values["description"])
    when = values.get("when")
    if "when" in values and when:
        _apply_when(note, when, assign)
    if "recurrence" in values:
        all_day = note.all_day
        rule = stored_rule(values["recurrence"], tz, all_day=all_day) if values["recurrence"] else ""
        try:
            validate_rrule(rule)
        except ValidationError:
            rule = note.recurrence  # an unparseable rule just isn't imported
        assign("recurrence", rule)
    if "reminder" in values:
        assign("remind_minutes_before", values["reminder"])
    if "color_id" in values:
        assign("color", GOOGLE_EVENT_COLORS.get(values["color_id"] or "", ""))
    return changed


def _apply_when(note, when, assign):
    deadline_only = note.pk is not None and note.starts_at is None and note.expires_at is not None
    if when["all_day"]:
        start = all_day_moment(parse_date(when["start"]))
        end = all_day_moment(parse_date(when["end"]))
        assign("all_day", True)
    else:
        start = parse_datetime(when["start"])
        end = parse_datetime(when["end"])
        assign("all_day", False)
    if deadline_only and start == end:
        # Keep a deadline-style note (end only) in that shape.
        assign("expires_at", end)
        return
    assign("starts_at", start)
    # A timed point in time is stored without an end; all-day notes keep
    # their inclusive last day (as the /events/ modal stores them).
    assign("expires_at", None if (not when["all_day"] and end == start) else end)
