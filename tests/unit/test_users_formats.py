from datetime import UTC, date, datetime
from unittest.mock import patch

import pytest
from django.template import Context, Template
from django.urls import reverse
from django.utils import translation
from django.utils.formats import get_format

from apps.events.tasks import _reminder_payload
from apps.users import formats
from apps.users.forms import ProfileForm

pytestmark = pytest.mark.django_db

MOMENT = datetime(2026, 12, 31, 14, 5, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset_active_formats():
    yield
    formats.deactivate()


@pytest.mark.parametrize("language", ["en", "ru"])
def test_empty_preferences_are_the_languages_own_django_formats(language):
    with translation.override(language):
        result = formats.display_formats()
        assert result.date == get_format("SHORT_DATE_FORMAT")
        assert result.time == get_format("TIME_FORMAT")
        assert result.datetime == get_format("SHORT_DATETIME_FORMAT")
    # English Django formats use a 12-hour clock ("P"), Russian a 24-hour one.
    assert result.hour12 is (language == "en")


def test_preferences_override_date_and_clock():
    with translation.override("en"):
        result = formats.display_formats("d.m.Y", formats.CLOCK_24)
    assert (result.date, result.time, result.datetime, result.hour12) == ("d.m.Y", "H:i", "d.m.Y H:i", False)

    with translation.override("ru"):
        result = formats.display_formats("", formats.CLOCK_12)
    assert (result.date, result.time, result.hour12) == ("d.m.Y", "g:i A", True)


def test_unknown_stored_values_count_as_unset():
    with translation.override("en"):
        assert formats.display_formats("j. F Y", "99") == formats.display_formats()


def test_js_date_falls_back_to_iso_for_patterns_js_cant_render():
    assert formats.DisplayFormats("j-n-Y", "H:i", "", False).js_date == "j-n-Y"
    assert formats.DisplayFormats(r"j \d\e F", "H:i", "", False).js_date == "Y-m-d"


def test_format_helpers_use_the_given_user(user):
    user.date_format, user.time_format = "Y-m-d", formats.CLOCK_12
    assert formats.format_date(date(2026, 12, 31), user=user) == "2026-12-31"
    assert formats.format_datetime(MOMENT, user=user) == "2026-12-31 2:05 PM"
    assert formats.format_time(MOMENT, user=user) == "2:05 PM"


def test_template_filters_follow_the_active_preferences(user):
    user.date_format, user.time_format = "d/m/Y", formats.CLOCK_24
    formats.activate(user)
    template = Template("{% load tz user_formats %}{{ value|utc|user_date }}|{{ value|utc|user_datetime }}|{{ value|utc|user_time }}")
    assert template.render(Context({"value": MOMENT})) == "31/12/2026|31/12/2026 14:05|14:05"


def test_profile_form_validates_format_choices(user):
    assert ProfileForm(instance=user, data={"date_format": "Y-m-d", "time_format": "12"}).is_valid()
    assert ProfileForm(instance=user, data={"date_format": "", "time_format": ""}).is_valid()
    form = ProfileForm(instance=user, data={"date_format": "Y/d/m", "time_format": "36"})
    assert not form.is_valid()
    assert {"date_format", "time_format"} <= set(form.errors)


def test_profile_saves_formats_and_pages_expose_them_to_js(client, user):
    client.force_login(user)
    response = client.post(reverse("users:profile"), {
        "first_name": "", "last_name": "", "timezone": "Europe/Vilnius", "date_format": "d.m.Y", "time_format": "24",
    })
    assert response.status_code == 302
    user.refresh_from_db()
    assert (user.date_format, user.time_format) == ("d.m.Y", "24")

    body = client.get(reverse("users:profile")).content.decode()
    assert 'data-date-format="d.m.Y"' in body
    assert 'data-hour12="0"' in body
    assert 'data-time-zone="Europe/Vilnius"' in body


def test_anonymous_requests_get_the_language_defaults(client, user):
    user.date_format, user.time_format = "Y-m-d", "24"
    user.save()
    client.force_login(user)
    client.get(reverse("users:profile"))
    client.logout()

    with translation.override("en"):
        body = client.get(reverse("content:home")).content.decode()
    assert 'data-date-format="m/d/Y"' in body
    assert 'data-hour12="1"' in body


def test_note_page_shows_dates_in_the_users_format(client, user, note_factory):
    user.date_format, user.time_format = "Y-m-d", "24"
    user.save()
    note = note_factory(title="Trip", starts_at=datetime(2026, 10, 5, 7, 30, tzinfo=UTC))
    client.force_login(user)

    body = client.get(reverse("content:note_detail", args=[note.public_id])).content.decode()
    assert "Starts 2026-10-05 07:30" in body


def test_reminder_text_uses_the_owners_formats(user, note_factory):
    user.date_format, user.time_format = "d.m.Y", "12"
    user.save()
    note = note_factory(title="Dentist", starts_at=datetime(2026, 10, 5, 15, 0, tzinfo=UTC), remind_minutes_before=15)
    note.refresh_from_db()

    with patch("apps.notifications.services.push_notification"), translation.override("en"):
        payload = _reminder_payload(note)
    assert payload["body"] == "Starts: 05.10.2026 3:00 PM"
