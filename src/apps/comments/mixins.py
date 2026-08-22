from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

from .models import Comment


class CommentableMixin(models.Model):
    """Adds a reverse generic relation to comments targeting this object.

    Mix into any model comments can attach to (apps.content.Note,
    apps.attachments.Attachment) instead of repeating the GenericRelation
    wiring in every package.
    """

    comments = GenericRelation(
        Comment, content_type_field="content_type", object_id_field="object_id",
    )

    class Meta:
        abstract = True
