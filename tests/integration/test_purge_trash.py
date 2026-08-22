import datetime
import os

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone

from apps.attachments.models import Attachment
from apps.comments.models import Comment
from apps.content.models import Note

pytestmark = pytest.mark.django_db


def test_purge_trash_only_removes_rows_older_than_cutoff(note_factory):
    stale = note_factory(title="Stale")
    fresh = note_factory(title="Fresh")

    Note.objects.filter(pk=stale.pk).update(deleted_at=timezone.now() - datetime.timedelta(days=40))
    Note.objects.filter(pk=fresh.pk).update(deleted_at=timezone.now() - datetime.timedelta(days=1))

    call_command("purge_trash", "--older-than", "30")

    assert not Note.objects.filter(pk=stale.pk).exists()
    assert Note.objects.filter(pk=fresh.pk).exists()


def test_purge_trash_dry_run_changes_nothing(note_factory):
    stale = note_factory(title="Stale")
    Note.objects.filter(pk=stale.pk).update(deleted_at=timezone.now() - datetime.timedelta(days=40))

    call_command("purge_trash", "--older-than", "30", "--dry-run")

    assert Note.objects.filter(pk=stale.pk).exists()


def test_purge_trash_removes_attachment_file_from_disk(user):
    upload = SimpleUploadedFile("doc.txt", b"hello", content_type="text/plain")
    attachment = Attachment.objects.create(owner=user, file=upload)
    file_path = attachment.file.path
    assert os.path.exists(file_path)

    Attachment.objects.filter(pk=attachment.pk).update(deleted_at=timezone.now() - datetime.timedelta(days=40))
    call_command("purge_trash", "--older-than", "30")

    assert not Attachment.objects.filter(pk=attachment.pk).exists()
    assert not os.path.exists(file_path)


def test_purge_trash_covers_every_soft_deletable_model(user, note_factory):
    """The command discovers models via SoftDeleteModel subclasses - this
    guards against a future package silently being left out."""
    note = note_factory()
    comment = Comment.objects.create(
        owner=user,
        content_type_id=_note_ct_id(),
        object_id=note.pk,
        body="stale comment",
    )
    Comment.objects.filter(pk=comment.pk).update(deleted_at=timezone.now() - datetime.timedelta(days=40))

    call_command("purge_trash", "--older-than", "30")

    assert not Comment.objects.filter(pk=comment.pk).exists()


def _note_ct_id():
    from django.contrib.contenttypes.models import ContentType

    return ContentType.objects.get_for_model(Note).pk
