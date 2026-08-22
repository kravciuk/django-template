import datetime

import pytest
from django.utils import timezone

from apps.attachments.models import Attachment
from apps.comments.models import Comment
from apps.common.enums import Visibility
from apps.content.models import Note
from apps.content.services import purge_stale_notes

pytestmark = pytest.mark.django_db


def test_note_default_visibility_is_public(note_factory):
    note = note_factory(title="Untitled")
    assert note.visibility == Visibility.PUBLIC


def test_tree_nesting_three_levels(note_factory):
    root = note_factory(title="Root")
    child = note_factory(title="Child", parent=root)
    grandchild = note_factory(title="Grandchild", parent=child)

    assert grandchild.depth == root.depth + 2
    descendants = set(Note.objects.get_descendants(root, include_self=True).values_list("pk", flat=True))
    assert descendants == {root.pk, child.pk, grandchild.pk}

    ancestors = list(Note.objects.get_ancestors(grandchild))
    assert [n.pk for n in ancestors] == [root.pk, child.pk]


def test_soft_delete_cascades_to_subtree_attachments_and_comments(note_factory, user):
    root = note_factory(title="Root")
    child = note_factory(title="Child", parent=root)

    attachment = Attachment.objects.create(
        owner=user, content_type_id=_note_ct_id(), object_id=child.pk, file=_dummy_file(),
    )
    comment = Comment.objects.create(
        owner=user, content_type_id=_note_ct_id(), object_id=child.pk, body="hi",
    )

    root.soft_delete()

    root.refresh_from_db()
    child.refresh_from_db()
    attachment.refresh_from_db()
    comment.refresh_from_db()

    assert root.deleted_at is not None
    assert child.deleted_at == root.deleted_at
    assert attachment.deleted_at == root.deleted_at
    assert comment.deleted_at == root.deleted_at


def test_restore_is_exact_round_trip(note_factory):
    root = note_factory(title="Root")
    child = note_factory(title="Child", parent=root)

    # A sibling trashed earlier and separately must NOT come back when the
    # root above is restored.
    other_root = note_factory(title="Other root")
    other_root.soft_delete()
    earlier_stamp = other_root.deleted_at

    root.soft_delete()
    root.restore()

    root.refresh_from_db()
    child.refresh_from_db()
    other_root.refresh_from_db()

    assert root.deleted_at is None
    assert child.deleted_at is None
    assert other_root.deleted_at == earlier_stamp  # untouched


def test_purge_stale_notes_skips_subtree_with_live_descendant(note_factory):
    root = note_factory(title="Root")
    child = note_factory(title="Child", parent=root)

    stale_cutoff = timezone.now() + datetime.timedelta(days=1)
    root.deleted_at = timezone.now() - datetime.timedelta(days=40)
    root.save(update_fields=["deleted_at"])
    # child stays alive (deleted_at=None) - root's subtree isn't fully stale.

    purged = purge_stale_notes(stale_cutoff, dry_run=True)

    assert purged == 0
    assert Note.objects.filter(pk__in=[root.pk, child.pk]).count() == 2


def test_purge_stale_notes_deletes_fully_stale_subtree(note_factory):
    root = note_factory(title="Root")
    child = note_factory(title="Child", parent=root)

    stamp = timezone.now() - datetime.timedelta(days=40)
    Note.objects.filter(pk__in=[root.pk, child.pk]).update(deleted_at=stamp)

    cutoff = timezone.now() - datetime.timedelta(days=30)
    purged = purge_stale_notes(cutoff)

    assert purged == 2
    assert not Note.objects.filter(pk__in=[root.pk, child.pk]).exists()


def _note_ct_id():
    from django.contrib.contenttypes.models import ContentType

    return ContentType.objects.get_for_model(Note).pk


def _dummy_file():
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile("note.txt", b"hello world", content_type="text/plain")
