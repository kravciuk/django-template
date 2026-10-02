import zoneinfo
from datetime import UTC, date, datetime, timedelta

import pytest
from django.core.exceptions import ValidationError

from apps.content.models import Note
from apps.events.recurrence import (
    MAX_OCCURRENCES,
    all_day_moment,
    build_rrule,
    next_occurrence_start,
    occurrences,
    parse_simple,
    validate_rrule,
)

VILNIUS = zoneinfo.ZoneInfo("Europe/Vilnius")


def _note(**kwargs):
    # Unsaved is enough - the recurrence helpers only read fields.
    return Note(title="Series", **kwargs)


def test_build_and_parse_simple_round_trip():
    rule = build_rrule("WEEKLY", 2, date(2027, 12, 31))
    assert rule == "FREQ=WEEKLY;INTERVAL=2;UNTIL=20271231T235959"
    assert parse_simple(rule) == {"freq": "WEEKLY", "interval": 2, "until": date(2027, 12, 31)}
    assert build_rrule("") == ""
    assert parse_simple("") == {}


def test_parse_simple_returns_none_for_rules_the_ui_cannot_show():
    assert parse_simple("FREQ=MONTHLY;BYDAY=1MO") is None
    assert parse_simple("FREQ=HOURLY") is None


@pytest.mark.parametrize("value", ["FREQ=NOPE", "DTSTART:20260101T000000\nRRULE:FREQ=DAILY", "garbage"])
def test_validate_rrule_rejects_invalid_rules(value):
    with pytest.raises(ValidationError):
        validate_rrule(value)


def test_validate_rrule_accepts_a_utc_until():
    validate_rrule("FREQ=WEEKLY;UNTIL=20271231T235959Z")


def test_yearly_occurrences_in_window():
    note = _note(starts_at=datetime(2026, 3, 10, 9, 0, tzinfo=VILNIUS), recurrence="FREQ=YEARLY")
    result = occurrences(note, datetime(2028, 1, 1, tzinfo=UTC), datetime(2029, 1, 1, tzinfo=UTC), VILNIUS)
    assert [start for start, _end in result] == [datetime(2028, 3, 10, 9, 0, tzinfo=VILNIUS)]


def test_weekly_with_until_stops():
    note = _note(starts_at=datetime(2026, 10, 1, 9, 0, tzinfo=VILNIUS), recurrence=build_rrule("WEEKLY", 1, date(2026, 10, 15)))
    result = occurrences(note, datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC), VILNIUS)
    assert len(result) == 3


def test_timed_occurrence_keeps_wall_clock_across_dst_and_duration():
    # Vilnius leaves summer time on the last Sunday of October.
    note = _note(
        starts_at=datetime(2026, 10, 20, 9, 0, tzinfo=VILNIUS),
        expires_at=datetime(2026, 10, 20, 10, 30, tzinfo=VILNIUS),
        recurrence="FREQ=WEEKLY",
    )
    result = occurrences(note, datetime(2026, 10, 19, tzinfo=UTC), datetime(2026, 11, 5, tzinfo=UTC), VILNIUS)
    starts = [timezone_free(start.astimezone(VILNIUS)) for start, _end in result]
    assert starts == [(2026, 10, 20, 9, 0), (2026, 10, 27, 9, 0), (2026, 11, 3, 9, 0)]
    assert all(end - start == timedelta(minutes=90) for start, end in result)


def timezone_free(value):
    return (value.year, value.month, value.day, value.hour, value.minute)


def test_monthly_on_the_31st_skips_short_months():
    note = _note(starts_at=datetime(2026, 1, 31, 9, 0, tzinfo=UTC), recurrence="FREQ=MONTHLY")
    result = occurrences(note, datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 6, 1, tzinfo=UTC), UTC)
    assert [start.month for start, _end in result] == [1, 3, 5]


def test_all_day_occurrences_keep_dates_and_span():
    note = _note(
        all_day=True,
        starts_at=all_day_moment(date(2026, 5, 1)),
        expires_at=all_day_moment(date(2026, 5, 3)),
        recurrence="FREQ=YEARLY",
    )
    result = occurrences(note, datetime(2027, 4, 1, tzinfo=VILNIUS), datetime(2027, 6, 1, tzinfo=VILNIUS), VILNIUS)
    assert result == [(all_day_moment(date(2027, 5, 1)), all_day_moment(date(2027, 5, 3)))]


def test_occurrence_spanning_into_the_window_is_included():
    note = _note(
        all_day=True,
        starts_at=all_day_moment(date(2026, 4, 28)),
        expires_at=all_day_moment(date(2026, 5, 2)),
        recurrence="FREQ=YEARLY",
    )
    result = occurrences(note, datetime(2026, 5, 1, tzinfo=UTC), datetime(2026, 5, 31, tzinfo=UTC), UTC)
    assert len(result) == 1


def test_expansion_is_capped():
    note = _note(starts_at=datetime(2000, 1, 1, tzinfo=UTC), recurrence="FREQ=DAILY")
    result = occurrences(note, datetime(2000, 1, 1, tzinfo=UTC), datetime(2010, 1, 1, tzinfo=UTC), UTC)
    assert len(result) == MAX_OCCURRENCES


def test_next_occurrence_start():
    note = _note(starts_at=datetime(2026, 3, 10, 9, 0, tzinfo=VILNIUS), recurrence="FREQ=YEARLY")
    after = datetime(2026, 6, 1, tzinfo=UTC)
    assert next_occurrence_start(note, after, VILNIUS) == datetime(2027, 3, 10, 9, 0, tzinfo=VILNIUS)
