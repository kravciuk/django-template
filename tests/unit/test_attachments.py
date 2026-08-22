import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction

from apps.attachments.enums import AttachmentKind
from apps.attachments.models import Attachment
from apps.attachments.utils import attachment_upload_to
from apps.content.models import Note
from libs.utils import sha256_of

pytestmark = pytest.mark.django_db


def test_metadata_populated_on_first_save(user, tiny_png_bytes):
    upload = SimpleUploadedFile("my photo.png", tiny_png_bytes, content_type="image/png")
    attachment = Attachment.objects.create(owner=user, file=upload, title="Cover shot")

    assert attachment.original_name == "my photo.png"
    assert attachment.mime_type == "image/png"
    assert attachment.kind == AttachmentKind.IMAGE
    assert attachment.size == len(tiny_png_bytes)
    assert attachment.checksum == sha256_of(io.BytesIO(tiny_png_bytes))
    assert attachment.width == 1 and attachment.height == 1


def test_metadata_not_recomputed_when_file_unchanged(user, tiny_png_bytes):
    upload = SimpleUploadedFile("photo.png", tiny_png_bytes, content_type="image/png")
    attachment = Attachment.objects.create(owner=user, file=upload)
    original_checksum = attachment.checksum

    attachment.title = "Renamed"
    attachment.save()
    attachment.refresh_from_db()

    assert attachment.checksum == original_checksum


def test_upload_to_never_leaks_the_original_filename(user):
    fake_instance = Attachment(owner=user)
    path = attachment_upload_to(fake_instance, "../../etc/passwd.txt")

    assert "etc" not in path
    assert "passwd" not in path
    assert path.endswith(".txt")
    assert path.startswith(f"attachments/{user.pk}/")


def test_standalone_attachment_without_a_target_saves_fine(user):
    upload = SimpleUploadedFile("doc.pdf", b"%PDF-1.4 fake", content_type="application/pdf")
    attachment = Attachment.objects.create(owner=user, file=upload)

    assert attachment.content_type_id is None
    assert attachment.object_id is None
    assert attachment.kind == AttachmentKind.DOCUMENT


def test_heic_upload_is_converted_to_jpeg_on_save(user):
    upload = SimpleUploadedFile("IMG_1234.HEIC", _heic_bytes(), content_type="image/heic")
    attachment = Attachment.objects.create(owner=user, file=upload)

    assert attachment.original_name == "IMG_1234.jpg"
    assert attachment.mime_type == "image/jpeg"
    assert attachment.kind == AttachmentKind.IMAGE
    assert attachment.file.name.endswith(".jpg")
    attachment.file.open("rb")
    try:
        assert attachment.file.read(3) == b"\xff\xd8\xff"  # JPEG magic bytes
    finally:
        attachment.file.close()


def test_only_one_cover_per_target(user, note_factory):
    note = note_factory()
    ct_id = _note_ct_id()

    Attachment.objects.create(
        owner=user, content_type_id=ct_id, object_id=note.pk, file=_dummy_file("a.txt"), is_cover=True,
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Attachment.objects.create(
                owner=user, content_type_id=ct_id, object_id=note.pk, file=_dummy_file("b.txt"), is_cover=True,
            )


def _note_ct_id():
    from django.contrib.contenttypes.models import ContentType

    return ContentType.objects.get_for_model(Note).pk


def _dummy_file(name):
    return SimpleUploadedFile(name, b"hello", content_type="text/plain")


def _heic_bytes():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (20, 20), color=(10, 20, 30)).save(buf, format="HEIF")
    return buf.getvalue()
