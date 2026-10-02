"""Reminder scheduling. Note.remind_minutes_before is the user-set relative
offset; ExpiryModel.remind_at holds the resulting *next* absolute fire time
(denormalized + indexed, so the beat task is a single cheap query). It is
recomputed after every Note save (signals.py) and after each delivery
(tasks.send_due_reminders), never edited directly.

json_data["reminded_at"] remembers the last delivered fire time, so a save
shortly after a delivery can't schedule that same reminder a second time.
"""

from datetime import datetime, timedelta

from constance import config
from django.utils import timezone

from apps.content.enums import NoteKind
from apps.content.models import Note
from apps.users.middleware import user_zoneinfo

from .recurrence import all_day_date, event_bounds, local_day_start, next_occurrence_start
from .services import is_document

DEFAULT_DOCUMENT_REMIND_DAYS = 14
# A reminder that came due less than this long ago is still delivered by
# the next beat run (every 5 min) even if the note is saved in between.
REMINDER_GRACE = timedelta(minutes=15)
REMINDED_AT_KEY = "reminded_at"


def owner_zone(note):
    return user_zoneinfo(note.owner) or timezone.get_default_timezone()


def reminder_offset(note):
    """The lead time before the event, or None for "no reminder". Documents
    without their own setting fall back to EVENTS_DOCUMENT_REMIND_DAYS."""
    if note.remind_minutes_before is not None:
        return timedelta(minutes=note.remind_minutes_before)
    if is_document(note):
        days = getattr(config, "EVENTS_DOCUMENT_REMIND_DAYS", DEFAULT_DOCUMENT_REMIND_DAYS)
        return timedelta(days=days) if days else None
    return None


def _single_start(note, tz):
    start, _end = event_bounds(note)
    if start is None:
        return None
    if note.all_day:
        return local_day_start(all_day_date(start), tz)
    return start


def next_reminder_at(note, after):
    """First reminder fire time strictly after `after`, or None."""
    if note.is_draft or note.deleted_at is not None or note.kind == NoteKind.NODE:
        return None
    offset = reminder_offset(note)
    if offset is None:
        return None
    tz = owner_zone(note)
    if note.recurrence and not is_document(note):
        occurrence = next_occurrence_start(note, after + offset, tz)
        return occurrence - offset if occurrence else None
    start = _single_start(note, tz)
    if start is None:
        return None
    fire_at = start - offset
    return fire_at if fire_at > after else None


def last_reminded_at(note):
    value = (note.json_data or {}).get(REMINDED_AT_KEY)
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def refresh_reminder(note, now=None):
    """Recompute and persist note.remind_at. Uses a queryset update, so it
    doesn't re-trigger post_save."""
    now = now or timezone.now()
    after = now - REMINDER_GRACE
    reminded = last_reminded_at(note)
    if reminded is not None and reminded > after:
        after = reminded
    remind_at = next_reminder_at(note, after)
    if remind_at != note.remind_at:
        Note.objects.filter(pk=note.pk).update(remind_at=remind_at)
        note.remind_at = remind_at
    return remind_at


def is_still_due(note):
    """Whether note.remind_at still matches the note's current reminder
    settings (they may have changed since it was computed - e.g. the
    EVENTS_DOCUMENT_REMIND_DAYS default, or a restored-from-trash row)."""
    if note.remind_at is None:
        return False
    return next_reminder_at(note, note.remind_at - timedelta(microseconds=1)) == note.remind_at


def mark_delivered(note, now):
    """After a delivery: remember it and schedule the next one. Never
    schedules into the past, so a long beat outage doesn't replay every
    missed occurrence of a recurring event."""
    delivered_at = note.remind_at
    json_data = dict(note.json_data or {})
    json_data[REMINDED_AT_KEY] = delivered_at.isoformat()
    remind_at = next_reminder_at(note, max(delivered_at, now))
    Note.objects.filter(pk=note.pk).update(remind_at=remind_at, json_data=json_data)
    note.remind_at, note.json_data = remind_at, json_data
    return remind_at
