import pytest
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.comments.models import Comment
from apps.content.models import Note

pytestmark = pytest.mark.django_db


def _ct_id(model):
    return ContentType.objects.get_for_model(model).pk


def _make_chain(depth, owner, target_ct_id, target_id):
    """Build a reply chain `depth` levels deep, bypassing clean() so we can
    also exercise the raw DB constraint independently of Python validation.
    """
    parent = None
    comment = None
    for _ in range(depth):
        comment = Comment(owner=owner, content_type_id=target_ct_id, object_id=target_id, body="x", parent=parent)
        comment.save()
        parent = comment
    return comment


def test_reply_depth_five_is_allowed(user, note_factory):
    note = note_factory()
    last = _make_chain(5, user, _ct_id(Note), note.pk)
    assert last.depth == 5


def test_reply_depth_six_rejected_by_clean(user, note_factory):
    note = note_factory()
    fifth = _make_chain(5, user, _ct_id(Note), note.pk)

    sixth = Comment(owner=user, content_type_id=_ct_id(Note), object_id=note.pk, body="too deep", parent=fifth)
    with pytest.raises(ValidationError):
        sixth.full_clean()


def test_reply_depth_six_rejected_by_db_constraint(user, note_factory):
    note = note_factory()
    fifth = _make_chain(5, user, _ct_id(Note), note.pk)

    sixth = Comment(owner=user, content_type_id=_ct_id(Note), object_id=note.pk, body="too deep", parent=fifth)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            sixth.save()  # bypasses clean() - constraint below must still catch it


def test_reply_to_comment_on_a_different_object_is_rejected(user, note_factory):
    note_a = note_factory(title="A")
    note_b = note_factory(title="B")

    parent = Comment.objects.create(owner=user, content_type_id=_ct_id(Note), object_id=note_a.pk, body="on A")
    reply = Comment(owner=user, content_type_id=_ct_id(Note), object_id=note_b.pk, body="on B", parent=parent)

    with pytest.raises(ValidationError):
        reply.full_clean()


def test_edited_at_only_set_when_body_actually_changes(user, note_factory):
    note = note_factory()
    comment = Comment.objects.create(owner=user, content_type_id=_ct_id(Note), object_id=note.pk, body="v1")
    assert comment.edited_at is None

    comment.refresh_from_db()
    comment.owner = comment.owner  # touch an unrelated field, no-op save
    comment.save()
    comment.refresh_from_db()
    assert comment.edited_at is None

    comment.body = "v2"
    comment.save()
    comment.refresh_from_db()
    assert comment.edited_at is not None
