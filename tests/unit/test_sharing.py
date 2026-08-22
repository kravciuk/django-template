import datetime

import pytest
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

from apps.common.enums import Visibility
from apps.content.models import Note
from apps.sharing.access import can_view
from apps.sharing.models import ShareLink

pytestmark = pytest.mark.django_db


def _make_link(note, **kwargs):
    return ShareLink.objects.create(
        owner=note.owner,
        content_type=ContentType.objects.get_for_model(Note),
        object_id=note.pk,
        **kwargs,
    )


def test_is_valid_true_by_default(note_factory):
    link = _make_link(note_factory())
    assert link.is_valid() is True


def test_is_valid_false_when_inactive(note_factory):
    link = _make_link(note_factory(), is_active=False)
    assert link.is_valid() is False


def test_is_valid_false_when_expired(note_factory):
    link = _make_link(note_factory(), expires_at=timezone.now() - datetime.timedelta(days=1))
    assert link.is_valid() is False


def test_is_valid_false_when_use_limit_reached(note_factory):
    link = _make_link(note_factory(), max_uses=1, used_count=1)
    assert link.is_valid() is False


def test_password_is_stored_hashed(note_factory):
    link = _make_link(note_factory())
    link.set_password("secret123")
    link.save()

    assert link.password != "secret123"
    assert link.check_password("secret123") is True
    assert link.check_password("wrong") is False


def test_can_view_matrix(note_factory, user, other_user):
    cases = [
        (Visibility.PUBLIC, None, False, True),
        (Visibility.UNLISTED, None, False, True),
        (Visibility.SHARED, None, False, False),
        (Visibility.SHARED, "valid_link", False, True),
        (Visibility.PRIVATE, None, False, False),
        (Visibility.PRIVATE, None, True, True),  # owner always sees their own
    ]
    for visibility, link_kind, as_owner, expected in cases:
        note = note_factory(visibility=visibility)
        share_link = _make_link(note) if link_kind == "valid_link" else None
        viewer = note.owner if as_owner else other_user
        assert can_view(note, viewer, share_link=share_link) is expected, (visibility, link_kind, as_owner)


def test_can_view_anonymous_never_sees_private(note_factory):
    note = note_factory(visibility=Visibility.PRIVATE)
    assert can_view(note, None) is False
