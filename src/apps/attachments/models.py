import mimetypes
from io import BytesIO
from pathlib import Path

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import models
from taggit.managers import TaggableManager

from apps.comments.mixins import CommentableMixin
from apps.common.models import ExpiryModel, OwnedModel, SoftDeleteModel, TimeStampedModel, VisibilityModel
from apps.sharing.mixins import ShareableMixin
from libs.utils import sha256_of

from .enums import AttachmentKind
from .utils import attachment_upload_to
from .validators import validate_upload_extension, validate_upload_size

DOCUMENT_MIME_PREFIXES = ("application/pdf", "application/msword", "application/vnd.", "text/")

# HEIC/HEIF (the default photo format on iPhones) isn't renderable in most
# browsers - converted to JPEG immediately on upload, not just for
# generated thumbnails, so the stored file itself is always web-safe.
HEIC_EXTENSIONS = {".heic", ".heif"}


class Attachment(
    TimeStampedModel, OwnedModel, VisibilityModel, SoftDeleteModel, ExpiryModel,
    CommentableMixin, ShareableMixin,
):
    """A file or photo. May stand on its own (content_type/object_id null)
    or be attached to any object - currently only apps.content.Note - via a
    generic relation. A direct FK to Note would make this package depend on
    apps.content, and Note.cover would then close that into a cycle; the
    generic target keeps apps.attachments self-contained like apps.comments
    and apps.sharing.
    """

    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    target = GenericForeignKey("content_type", "object_id")

    position = models.PositiveIntegerField(default=0)
    is_cover = models.BooleanField(
        default=False, help_text="Cover image/file for its target (e.g. an album note).",
    )

    file = models.FileField(
        upload_to=attachment_upload_to,
        max_length=500,
        validators=[validate_upload_size, validate_upload_extension],
    )
    kind = models.CharField(
        max_length=16, choices=AttachmentKind.choices, default=AttachmentKind.OTHER, db_index=True,
    )
    original_name = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=120, blank=True)
    size = models.PositiveBigIntegerField(default=0)
    checksum = models.CharField(max_length=64, blank=True, db_index=True)  # sha256
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)

    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)

    tags = TaggableManager(blank=True)

    class Meta:
        ordering = ["position", "id"]
        indexes = [models.Index(fields=["content_type", "object_id", "position"])]
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id"],
                condition=models.Q(is_cover=True),
                name="attachments_one_cover_per_target",
            ),
        ]

    def __str__(self):
        return self.title or self.original_name or f"Attachment #{self.pk}"

    def save(self, *args, **kwargs):
        if self.file and (self._state.adding or self._file_changed()):
            self._populate_file_metadata()
        super().save(*args, **kwargs)

    def _file_changed(self):
        if not self.pk:
            return True
        original = Attachment.objects.filter(pk=self.pk).values_list("file", flat=True).first()
        return original != self.file.name

    def _convert_heic_to_jpeg(self, f, name):
        """Re-encodes a HEIC/HEIF upload as JPEG, in memory, before it's
        ever written to storage. Relies on apps.attachments.apps having
        already called pillow_heif.register_heif_opener() so Pillow can
        open the source at all.
        """
        from PIL import Image

        f.seek(0)
        image = Image.open(f)
        image = image.convert("RGB")  # JPEG has no alpha/other-mode support
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        new_name = Path(name).with_suffix(".jpg").name
        return ContentFile(buffer.getvalue(), name=new_name)

    def _populate_file_metadata(self):
        """Runs only when the file itself changed (see save()), so editing
        title/description on an existing attachment doesn't re-hash a large
        file for nothing. Must run BEFORE the file is actually written to
        storage (i.e. before super().save()) - at this point self.file.name
        is still the client's original upload name, which is exactly what
        we want to capture into original_name; Django's FileField.pre_save()
        (called from within super().save()) is what later rewrites it to
        the randomized upload_to path.
        """
        f = self.file
        name = getattr(f, "name", "") or ""
        if Path(name).suffix.lower() in HEIC_EXTENSIONS:
            f = self._convert_heic_to_jpeg(f, name)
            self.file = f

        self.original_name = getattr(f, "name", "").rsplit("/", 1)[-1]
        guessed_type, _ = mimetypes.guess_type(self.original_name)
        self.mime_type = guessed_type or ""
        self.size = f.size or 0

        f.seek(0)
        self.checksum = sha256_of(f)
        f.seek(0)

        if self.mime_type.startswith("image/"):
            self.kind = AttachmentKind.IMAGE
            try:
                from PIL import Image

                with Image.open(f) as img:
                    self.width, self.height = img.size
            except Exception:
                pass
            finally:
                f.seek(0)
        elif self.mime_type.startswith("audio/"):
            self.kind = AttachmentKind.AUDIO
        elif self.mime_type.startswith("video/"):
            self.kind = AttachmentKind.VIDEO
        elif self.mime_type.startswith(DOCUMENT_MIME_PREFIXES):
            self.kind = AttachmentKind.DOCUMENT
        else:
            self.kind = AttachmentKind.OTHER
