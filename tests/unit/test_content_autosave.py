from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.common.enums import ContentFormat, Visibility
from apps.content.enums import NoteKind
from apps.content.models import Note
from apps.content.services import soft_delete_stale_drafts
from apps.sharing.access import can_view

pytestmark = pytest.mark.django_db


def _autosave_fields(**overrides):
    fields = {
        "title": "Draft in progress",
        "kind": NoteKind.NOTE,
        "body_format": ContentFormat.PLAIN,
        "body": "still typing",
        "visibility": Visibility.PUBLIC,
        "tags": "",
    }
    fields.update(overrides)
    return fields


def test_autosave_add_requires_login(client):
    response = client.post(reverse("content:note_autosave_add"), _autosave_fields())
    assert response.status_code == 302
    assert "/admin/login/" in response.url


def test_autosave_add_creates_draft_note(client, user):
    client.force_login(user)
    response = client.post(reverse("content:note_autosave_add"), _autosave_fields())

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True

    note = Note.objects.get(public_id=data["public_id"])
    assert note.is_draft is True
    assert note.owner_id == user.id
    assert note.title == "Draft in progress"


def test_autosave_add_accepts_blank_title_and_body(client, user):
    client.force_login(user)
    response = client.post(reverse("content:note_autosave_add"), _autosave_fields(title="", body=""))

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_autosave_edit_updates_the_same_row_no_duplicate(client, user):
    client.force_login(user)
    first = client.post(reverse("content:note_autosave_add"), _autosave_fields(title="v1")).json()

    edit_url = reverse("content:note_autosave_edit", args=[first["public_id"]])
    second = client.post(edit_url, _autosave_fields(title="v2")).json()

    assert second["public_id"] == first["public_id"]
    assert Note.objects.count() == 1
    note = Note.objects.get(public_id=first["public_id"])
    assert note.title == "v2"
    assert note.is_draft is True


def test_autosave_edit_forbidden_for_non_owner(client, note_factory, other_user):
    note = note_factory(title="Mine")

    client.force_login(other_user)
    response = client.post(reverse("content:note_autosave_edit", args=[note.public_id]), _autosave_fields())

    assert response.status_code == 403


def test_autosave_does_not_flip_a_published_note_back_to_draft(client, user, note_factory):
    note = note_factory(title="Published", owner=user, visibility=Visibility.PUBLIC)
    assert note.is_draft is False

    client.force_login(user)
    client.post(reverse("content:note_autosave_edit", args=[note.public_id]), _autosave_fields(title="Edited live"))

    note.refresh_from_db()
    assert note.is_draft is False
    assert note.title == "Edited live"


def test_final_submit_after_autosave_publishes_the_same_row(client, user):
    client.force_login(user)
    draft = client.post(reverse("content:note_autosave_add"), _autosave_fields(title="Draft")).json()

    response = client.post(
        reverse("content:note_edit", args=[draft["public_id"]]),
        _autosave_fields(title="Final"),
    )

    assert response.status_code == 302
    assert Note.objects.count() == 1
    note = Note.objects.get(public_id=draft["public_id"])
    assert note.is_draft is False
    assert note.title == "Final"


def test_can_view_hides_draft_from_everyone_but_owner(note_factory, user, other_user):
    draft = note_factory(title="WIP", owner=user, visibility=Visibility.PUBLIC, is_draft=True)

    assert can_view(draft, user) is True
    assert can_view(draft, other_user) is False
    assert can_view(draft, None) is False


def test_home_excludes_public_drafts(client, note_factory, user):
    note_factory(title="Draft", owner=user, visibility=Visibility.PUBLIC, is_draft=True)
    published = note_factory(title="Published", owner=user, visibility=Visibility.PUBLIC, is_draft=False)

    response = client.get(reverse("content:home"))

    titles = [entry["note"].title for entry in response.context["entries"]]
    assert titles == ["Published"]


def test_soft_delete_stale_drafts_trashes_only_old_abandoned_drafts(note_factory):
    stale_draft = note_factory(title="Abandoned", is_draft=True)
    Note.objects.filter(pk=stale_draft.pk).update(updated_at=timezone.now() - timedelta(days=30))

    fresh_draft = note_factory(title="Just started", is_draft=True)
    published = note_factory(title="Published", is_draft=False)
    Note.objects.filter(pk=published.pk).update(updated_at=timezone.now() - timedelta(days=30))

    count = soft_delete_stale_drafts(timezone.now() - timedelta(days=7))

    assert count == 1
    stale_draft.refresh_from_db()
    fresh_draft.refresh_from_db()
    published.refresh_from_db()
    assert stale_draft.deleted_at is not None
    assert fresh_draft.deleted_at is None
    assert published.deleted_at is None
