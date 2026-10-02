"""RRULE handling for recurring calendar notes (Note.recurrence).

Rules are expanded in the owner's *local wall-clock time* and only then made
timezone-aware, so a weekly 09:00 event stays at 09:00 across DST changes.
Note.recurrence holds the RRULE body only (no DTSTART) - the series starts
at the note's own start (see event_bounds). UNTIL is written as a naive
local end-of-day by build_rrule; any timezone suffix on an imported rule is
ignored (treated as local) rather than rejected.
"""

from datetime import UTC, date, datetime, time, timedelta
from itertools import islice

from dateutil.rrule import rrulestr
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

FREQUENCIES = ("DAILY", "WEEKLY", "MONTHLY", "YEARLY")
# Upper bound on expanded occurrences per call - a FREQ=DAILY rule over a
# multi-year window must not turn one feed request into an unbounded loop.
MAX_OCCURRENCES = 1000
# Only these RRULE parts map onto the simple repeat controls (frequency,
# "every N", "until"); anything else is shown as a read-only custom rule.
SIMPLE_RULE_PARTS = {"FREQ", "INTERVAL", "UNTIL"}


def _parse(value, dtstart):
    return rrulestr(value, dtstart=dtstart, ignoretz=True)


def validate_rrule(value):
    if not value:
        return
    if value.upper().startswith(("DTSTART", "RRULE:")) or "\n" in value:
        raise ValidationError(_("Enter only the repeat rule itself, e.g. FREQ=WEEKLY."))
    try:
        _parse(value, datetime(2000, 1, 1))
    except (ValueError, TypeError) as exc:
        raise ValidationError(_("Invalid repeat rule.")) from exc


def build_rrule(freq, interval=1, until=None):
    """RRULE body for the simple repeat controls. `until` is an inclusive
    local date (or None)."""
    if not freq:
        return ""
    parts = [f"FREQ={freq}"]
    if interval and interval > 1:
        parts.append(f"INTERVAL={interval}")
    if until:
        parts.append(f"UNTIL={until:%Y%m%d}T235959")
    return ";".join(parts)


def parse_simple(value):
    """{freq, interval, until} for a rule build_rrule could have produced,
    `{}` for no rule, or None for a rule the simple controls can't show."""
    if not value:
        return {}
    try:
        parts = dict(part.split("=", 1) for part in value.upper().split(";") if part)
    except ValueError:
        return None
    if set(parts) - SIMPLE_RULE_PARTS or parts.get("FREQ") not in FREQUENCIES:
        return None
    try:
        interval = int(parts.get("INTERVAL", "1"))
        until = parts.get("UNTIL")
        until = datetime.strptime(until[:8], "%Y%m%d").date() if until else None
    except ValueError:
        return None
    return {"freq": parts["FREQ"], "interval": interval, "until": until}


def event_bounds(note):
    """(start, end) of a note's own calendar placement - start falls back to
    expires_at for a note that only has an end/deadline; end is None for a
    single point in time."""
    start = note.starts_at or note.expires_at
    end = note.expires_at if note.starts_at else None
    return start, end


def all_day_date(value):
    """The calendar date an all-day value stands for (stored as UTC
    midnight, see Note.all_day)."""
    return value.astimezone(UTC).date()


def all_day_moment(day):
    """Inverse of all_day_date: a date -> the UTC-midnight datetime stored."""
    return datetime.combine(day, time.min, tzinfo=UTC)


def occurrences(note, window_start, window_end, tz=None):
    """(start, end) pairs of a recurring note's occurrences overlapping
    [window_start, window_end). Values use the same storage conventions as
    the note itself (aware datetimes; UTC midnight + inclusive end day for
    all-day notes)."""
    start, end = event_bounds(note)
    if start is None or not note.recurrence:
        return []
    tz = tz or timezone.get_current_timezone()

    if note.all_day:
        first_day = all_day_date(start)
        span = (all_day_date(end) - first_day) if end else timedelta(0)
        rule = _parse(note.recurrence, datetime.combine(first_day, time.min))
        lower = datetime.combine(timezone.localtime(window_start, tz).date() - span, time.min)
        upper = datetime.combine(timezone.localtime(window_end, tz).date(), time.min)
        result = []
        for occurrence in islice(rule.xafter(lower, inc=True), MAX_OCCURRENCES):
            if occurrence >= upper:
                break
            day = occurrence.date()
            result.append((all_day_moment(day), all_day_moment(day + span) if end else None))
        return result

    duration = (end - start) if end else timedelta(0)
    local_start = timezone.localtime(start, tz).replace(tzinfo=None)
    rule = _parse(note.recurrence, local_start)
    lower = timezone.localtime(window_start - duration, tz).replace(tzinfo=None)
    upper = timezone.localtime(window_end, tz).replace(tzinfo=None)
    result = []
    for occurrence in islice(rule.xafter(lower, inc=True), MAX_OCCURRENCES):
        if occurrence >= upper:
            break
        occurrence_start = occurrence.replace(tzinfo=tz)
        result.append((occurrence_start, occurrence_start + duration if end else None))
    return result


def next_occurrence_start(note, after, tz=None):
    """Start of the first occurrence strictly after `after`, or None. For an
    all-day note that's local midnight of the occurrence date in `tz`."""
    start, _end = event_bounds(note)
    if start is None or not note.recurrence:
        return None
    tz = tz or timezone.get_current_timezone()
    if note.all_day:
        rule = _parse(note.recurrence, datetime.combine(all_day_date(start), time.min))
        # Compare in local dates: the occurrence "starts" at local midnight.
        local_after = timezone.localtime(after, tz).replace(tzinfo=None)
        occurrence = rule.after(local_after, inc=False)
        return occurrence.replace(tzinfo=tz) if occurrence else None
    rule = _parse(note.recurrence, timezone.localtime(start, tz).replace(tzinfo=None))
    occurrence = rule.after(timezone.localtime(after, tz).replace(tzinfo=None), inc=False)
    return occurrence.replace(tzinfo=tz) if occurrence else None


def local_day_start(day: date, tz):
    return datetime.combine(day, time.min, tzinfo=tz)
