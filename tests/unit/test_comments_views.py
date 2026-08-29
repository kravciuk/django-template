import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from apps.comments.models import Comment
from apps.common.enums import Visibility
from apps.content.models import Note

pytestmark = pytest.mark.django_db


def _ct_id(model):
    return ContentType.objects.get_for_model(model).pk


def _make_chain(depth, owner, note):
    """Build a `depth`-level reply chain directly on the model, mirroring
    tests/unit/test_comments.py's helper - lets a view test start from an
    already-deep thread without going through five HTTP round-trips."""
    parent = None
    comment = None
    for i in range(depth):
        comment = Comment.objects.create(
            owner=owner, content_type_id=_ct_id(Note), object_id=note.pk, body=f"level {i + 1}", parent=parent,
        )
        parent = comment
    return comment


def test_anonymous_sees_thread_but_no_compose_form(client, note_factory, user):
    note = note_factory(visibility=Visibility.PUBLIC)
    Comment.objects.create(owner=user, content_type_id=_ct_id(Note), object_id=note.pk, body="hello")

    response = client.get(reverse("content:note_detail", args=[note.public_id]))

    assert response.context["comment_form"] is None
    assert "hello" in response.content.decode()
    assert 'class="comment-form"' not in response.content.decode()


def test_owner_can_create_reply_edit_and_delete_a_comment(client, note_factory, user):
    note = note_factory(visibility=Visibility.PUBLIC)
    client.force_login(user)

    create_url = reverse("comments:create", args=["note", note.public_id])
    response = client.post(create_url, {"body": "top level"})
    assert response.status_code == 200
    comment = Comment.objects.get(content_type_id=_ct_id(Note), object_id=note.pk)
    assert comment.body == "top level"
    assert comment.owner_id == user.id
    assert comment.ip is not None

    reply_url = reverse("comments:reply", args=[comment.pk])
    response = client.get(reply_url)
    assert response.status_code == 200
    response = client.post(reply_url, {"body": "a reply"})
    assert response.status_code == 200
    reply = Comment.objects.get(body="a reply")
    assert reply.parent_id == comment.pk
    assert reply.depth == 2

    edit_url = reverse("comments:edit", args=[comment.pk])
    response = client.get(edit_url)
    assert response.status_code == 200
    response = client.post(edit_url, {"body": "edited body"})
    assert response.status_code == 200
    comment.refresh_from_db()
    assert comment.body == "edited body"
    assert comment.edited_at is not None

    delete_url = reverse("comments:delete", args=[reply.pk])
    response = client.post(delete_url)
    assert response.status_code == 200
    reply.refresh_from_db()
    assert reply.is_trashed


def test_anonymous_post_is_rejected(client, note_factory):
    note = note_factory(visibility=Visibility.PUBLIC)
    response = client.post(reverse("comments:create", args=["note", note.public_id]), {"body": "nope"})
    assert response.status_code == 403
    assert not Comment.objects.filter(content_type_id=_ct_id(Note), object_id=note.pk).exists()


def test_non_owner_gets_403_on_edit_and_delete(client, note_factory, user, other_user):
    note = note_factory(visibility=Visibility.PUBLIC)
    comment = Comment.objects.create(owner=user, content_type_id=_ct_id(Note), object_id=note.pk, body="mine")

    client.force_login(other_user)
    assert client.get(reverse("comments:edit", args=[comment.pk])).status_code == 403
    assert client.post(reverse("comments:edit", args=[comment.pk]), {"body": "hijacked"}).status_code == 403
    assert client.post(reverse("comments:delete", args=[comment.pk])).status_code == 403

    comment.refresh_from_db()
    assert comment.body == "mine"
    assert not comment.is_trashed


def test_private_note_thread_404s_for_non_owner_even_hit_directly(client, note_factory, other_user):
    note = note_factory(visibility=Visibility.PRIVATE)

    client.force_login(other_user)
    response = client.get(reverse("comments:thread", args=["note", note.public_id]))
    assert response.status_code == 404


def test_reply_past_the_depth_cap_returns_form_errors_not_a_crash(client, note_factory, user):
    note = note_factory(visibility=Visibility.PUBLIC)
    deepest = _make_chain(5, user, note)

    client.force_login(user)
    response = client.post(reverse("comments:reply", args=[deepest.pk]), {"body": "too deep"})

    assert response.status_code == 200
    assert response.context["form"].errors
    assert not Comment.objects.filter(body="too deep").exists()


def test_soft_deleting_a_comment_with_alive_replies_keeps_a_placeholder_and_children(client, note_factory, user):
    note = note_factory(visibility=Visibility.PUBLIC)
    parent = Comment.objects.create(owner=user, content_type_id=_ct_id(Note), object_id=note.pk, body="parent")
    child = Comment.objects.create(
        owner=user, content_type_id=_ct_id(Note), object_id=note.pk, body="child", parent=parent,
    )

    client.force_login(user)
    response = client.post(reverse("comments:delete", args=[parent.pk]))

    assert response.status_code == 200
    content = response.content.decode()
    assert "[deleted]" in content
    assert "child" in content
    parent.refresh_from_db()
    assert parent.is_trashed
    child.refresh_from_db()
    assert not child.is_trashed


def test_soft_deleting_a_leaf_comment_removes_it(client, note_factory, user):
    note = note_factory(visibility=Visibility.PUBLIC)
    comment = Comment.objects.create(owner=user, content_type_id=_ct_id(Note), object_id=note.pk, body="leaf")

    client.force_login(user)
    response = client.post(reverse("comments:delete", args=[comment.pk]))

    assert response.status_code == 200
    assert response.content.decode() == ""
