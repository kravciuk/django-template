from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.common.models import OwnedModel, SoftDeleteModel, TimeStampedModel

# The DB-level CheckConstraint below hardcodes 5 (changing it needs a
# migration either way); this setting only lets you tighten the limit
# further without one.
DEFAULT_MAX_DEPTH = 5


def get_max_depth():
    return getattr(settings, "COMMENTS_MAX_DEPTH", DEFAULT_MAX_DEPTH)


class Comment(TimeStampedModel, OwnedModel, SoftDeleteModel):
    """A comment attached to any object via a generic relation (currently
    apps.content.Note and apps.attachments.Attachment).

    Nesting is capped at get_max_depth() (spec: 5 levels). This is a plain
    self-FK rather than treebeard: the depth cap makes recursion trivially
    bounded, so the extra dependency and a denormalized `path` column
    aren't worth it here - contrast apps.content.Note, which is genuinely
    unbounded and does use treebeard.
    """

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    target = GenericForeignKey("content_type", "object_id")

    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="replies",
    )
    depth = models.PositiveSmallIntegerField(default=1, editable=False)

    body = models.TextField()
    ip = models.GenericIPAddressField(null=True, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["content_type", "object_id", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(depth__gte=1) & models.Q(depth__lte=5),
                name="comments_comment_depth_max_5",
            ),
        ]

    def __str__(self):
        return f"Comment #{self.pk or 'new'} on {self.content_type_id}:{self.object_id}"

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._original_body = instance.body
        return instance

    def clean(self):
        super().clean()
        if self.parent_id:
            if (
                self.parent.content_type_id != self.content_type_id
                or self.parent.object_id != self.object_id
            ):
                raise ValidationError("A reply must target the same object as its parent comment.")
            if self.parent.depth + 1 > get_max_depth():
                raise ValidationError(f"Comment nesting is limited to {get_max_depth()} levels.")

    def save(self, *args, **kwargs):
        self.depth = self.parent.depth + 1 if self.parent_id else 1
        if not self._state.adding and getattr(self, "_original_body", None) not in (None, self.body):
            self.edited_at = timezone.now()
        super().save(*args, **kwargs)
        self._original_body = self.body
