"""Per-user date/time display formats (User.date_format/time_format).

An empty preference means "the active language's own Django formats"
(SHORT_DATE_FORMAT/TIME_FORMAT/SHORT_DATETIME_FORMAT), so a user who never
touches the profile sees exactly what Django would show.

UserFormatsMiddleware activates the logged-in user's preferences per request
(like timezone.activate()), which the `user_date`/`user_datetime`/`user_time`
template filters (templatetags/user_formats.py) and the `display_formats`
context processor read. Background code has no request - it passes the
recipient explicitly (format_date(value, user=...)).
"""
from dataclasses import dataclass
from datetime import datetime

from asgiref.local import Local
from django.template.defaultfilters import date as date_filter
from django.utils import dateformat
from django.utils.formats import get_format
from django.utils.translation import gettext as _

# Django `date` filter patterns - also valid flatpickr formats (d/m/Y mean
# the same there), which the date pickers rely on.
DATE_FORMATS = ["d.m.Y", "d/m/Y", "m/d/Y", "Y-m-d"]

CLOCK_24 = "24"
CLOCK_12 = "12"
TIME_FORMATS = {CLOCK_24: "H:i", CLOCK_12: "g:i A"}

# Tokens of a Django format that render a 12-hour clock.
TWELVE_HOUR_TOKENS = set("aAgPh")
# Tokens the JS side (display_formats.js, flatpickr) can render for a date.
JS_DATE_TOKENS = set("djmnYy")
JS_FALLBACK_DATE_FORMAT = "Y-m-d"

# A date whose day can't be mistaken for a month, for the profile examples.
EXAMPLE_MOMENT = datetime(2026, 12, 31, 14, 30)

_active = Local()


@dataclass(frozen=True)
class DisplayFormats:
    date: str
    time: str
    datetime: str
    hour12: bool

    @property
    def js_date(self):
        """`date` if the JS formatters can render it, else ISO order."""
        return self.date if _tokens(self.date) <= JS_DATE_TOKENS else JS_FALLBACK_DATE_FORMAT


def _tokens(fmt):
    """Format letters of a Django date format, skipping backslash escapes."""
    letters, escaped = set(), False
    for char in fmt:
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char.isalpha():
            letters.add(char)
    return letters


def uses_12_hour_clock(time_format):
    return bool(_tokens(time_format) & TWELVE_HOUR_TOKENS)


def display_formats(date_format="", time_format=""):
    """Effective formats for these preferences in the active language.
    Unknown stored values (e.g. typed in via the admin) count as unset."""
    if date_format not in DATE_FORMATS:
        date_format = ""
    if time_format not in TIME_FORMATS:
        time_format = ""
    date = date_format or get_format("SHORT_DATE_FORMAT")
    time = TIME_FORMATS.get(time_format) or get_format("TIME_FORMAT")
    if date_format or time_format:
        combined = f"{date} {time}"
    else:
        combined = get_format("SHORT_DATETIME_FORMAT")
    return DisplayFormats(date=date, time=time, datetime=combined, hour12=uses_12_hour_clock(time))


def user_display_formats(user):
    return display_formats(getattr(user, "date_format", ""), getattr(user, "time_format", ""))


def activate(user):
    _active.value = (getattr(user, "date_format", ""), getattr(user, "time_format", ""))


def deactivate():
    if hasattr(_active, "value"):
        del _active.value


def active_display_formats():
    return display_formats(*getattr(_active, "value", ("", "")))


def _formats_for(user):
    return user_display_formats(user) if user is not None else active_display_formats()


def format_date(value, user=None):
    return dateformat.format(value, _formats_for(user).date)


def format_datetime(value, user=None):
    return dateformat.format(value, _formats_for(user).datetime)


def format_time(value, user=None):
    return dateformat.format(value, _formats_for(user).time)


def _pattern_label(fmt):
    return "".join({"d": "DD", "m": "MM", "Y": "YYYY"}.get(char, char) for char in fmt)


def date_format_choices():
    """ProfileForm options, each with an example. Built per form instance:
    the default's example follows the active language."""
    default_example = date_filter(EXAMPLE_MOMENT.date(), "SHORT_DATE_FORMAT")
    return [
        ("", _("Language default (%(example)s)") % {"example": default_example}),
        *(
            (fmt, f"{date_filter(EXAMPLE_MOMENT.date(), fmt)} ({_pattern_label(fmt)})")
            for fmt in DATE_FORMATS
        ),
    ]


def time_format_choices():
    def example(fmt):
        return date_filter(EXAMPLE_MOMENT, fmt)

    return [
        ("", _("Language default (%(example)s)") % {"example": example("TIME_FORMAT")}),
        (CLOCK_24, _("24-hour (%(example)s)") % {"example": example(TIME_FORMATS[CLOCK_24])}),
        (CLOCK_12, _("12-hour (%(example)s)") % {"example": example(TIME_FORMATS[CLOCK_12])}),
    ]
