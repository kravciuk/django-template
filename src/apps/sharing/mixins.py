from django.contrib.contenttypes.fields import GenericRelation
from django.db import models

from .models import ShareLink


class ShareableMixin(models.Model):
    """Adds a reverse generic relation to share links targeting this object.

    Mix into any model that can be shared via a generated link
    (apps.content.Note, apps.attachments.Attachment).
    """

    share_links = GenericRelation(
        ShareLink, content_type_field="content_type", object_id_field="object_id",
    )

    class Meta:
        abstract = True
