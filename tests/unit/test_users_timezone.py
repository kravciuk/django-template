from datetime import UTC, datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.common.enums import ContentFormat, Visibility
from apps.content.enums import NoteKind
from apps.content.models import Note
from apps.users.forms import ProfileForm

pytestmark = pytest.mark.django_db


def test_profile_form_accepts_known_zone_and_rejects_unknown(user):
    assert ProfileForm(instance=user, data={"timezone": "Europe/Vilnius"}).is_valid()
    assert ProfileForm(instance=user, data={"timezone": ""}).is_valid()
    form = ProfileForm(instance=user, data={"timezone": "Mars/Olympus"})
    assert not form.is_valid()
    assert "timezone" in form.errors


def test_profile_saves_timezone(client, user):
    client.force_login(user)
    response = client.post(reverse("users:profile"), {"first_name": "", "last_name": "", "timezone": "Asia/Tokyo"})
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.timezone == "Asia/Tokyo"


def test_middleware_activates_the_users_zone(client, user):
    user.timezone = "Europe/Vilnius"
    user.save()
    client.force_login(user)
    response = client.get(reverse("events:home"))
    assert response.context["user_time_zone"] == "Europe/Vilnius"


def test_without_a_profile_zone_the_default_applies(client, user):
    client.force_login(user)
    response = client.get(reverse("events:home"))
    assert response.context["user_time_zone"] == timezone.get_default_timezone_name()


def test_note_form_datetime_is_read_in_the_users_zone(client, user):
    user.timezone = "Europe/Vilnius"
    user.save()
    client.force_login(user)
    response = client.post(reverse("content:note_add"), {
        "title": "Meeting", "kind": NoteKind.NOTE, "body_format": ContentFormat.PLAIN, "body": "",
        "visibility": Visibility.PRIVATE, "starts_at": "2026-10-05T10:00", "use_default_color": "on",
    })
    assert response.status_code == 302, response.content
    note = Note.objects.get(title="Meeting")
    assert note.starts_at == datetime(2026, 10, 5, 7, 0, tzinfo=UTC)  # 10:00 EEST
