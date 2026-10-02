from datetime import timedelta

from django import template
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from apps.events.services import calendar_entries

register = template.Library()

UPCOMING_DAYS = 7
UPCOMING_LIMIT = 10


@register.inclusion_tag("events/_upcoming_events.html", takes_context=True)
def upcoming_events(context, days=UPCOMING_DAYS, limit=UPCOMING_LIMIT):
    """The next `days` days of the viewer's calendar, for the home page -
    a template tag (not HomeView context) so apps.content doesn't depend on
    apps.events."""
    user = context["request"].user
    if not user.is_authenticated:
        return {"entries": [], "days": days}
    now = timezone.now()
    today = timezone.localdate()
    entries = [
        entry for entry in calendar_entries(user, now, now + timedelta(days=days))
        if _ends_on_or_after(entry, now, today)
    ]
    # ISO strings in one zone sort chronologically; an all-day date sorts
    # ahead of that same day's timed entries.
    entries.sort(key=lambda entry: entry["start"])
    return {"entries": [_display(entry) for entry in entries[:limit]], "days": days}


def _parse(value):
    if value is None:
        return None
    if len(value) == 10:
        return parse_date(value)
    return parse_datetime(value)


def _ends_on_or_after(entry, now, today):
    # calendar_entries pads its query window for all-day values; drop what
    # actually ended before now.
    end = _parse(entry["end"]) or _parse(entry["start"])
    if entry["allDay"]:
        return end > today if entry["end"] else end >= today
    return end >= now


def _display(entry):
    start = _parse(entry["start"])
    return {
        "title": entry["title"],
        "start": start,
        "all_day": entry["allDay"],
        "url": entry["extendedProps"]["detail_url"],
        "color": entry["backgroundColor"],
        "source": entry["extendedProps"]["source"],
    }
