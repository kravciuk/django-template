import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from .enums import Visibility
from .managers import SoftDeleteManager

DEFAULT_TRASH_RETENTION_DAYS = 30


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class OwnedModel(models.Model):
    """Single owner per object - the spec explicitly rules out a separate
    ACL system, so Django's own FK-based ownership is enough."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
    )

    class Meta:
        abstract = True


class PublicIdModel(models.Model):
    """A non-sequential, non-guessable public identifier.

    Used instead of the primary key wherever an object may be reached from
    outside the admin (unlisted visibility, future public URLs) - an
    autoincrement id would let anyone enumerate every row in the table just
    by walking integers.
    """

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    class Meta:
        abstract = True


class VisibilityModel(PublicIdModel):
    visibility = models.CharField(
        max_length=16,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
        db_index=True,
    )

    class Meta:
        abstract = True


class SoftDeleteModel(models.Model):
    """Trash-can behaviour: deletion just stamps `deleted_at`; a management
    command (apps.common.management.commands.purge_trash) hard-deletes rows
    past the retention window. Nothing disappears silently before that."""

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = SoftDeleteManager()

    class Meta:
        abstract = True

    @property
    def is_trashed(self):
        return self.deleted_at is not None

    @property
    def purge_at(self):
        if self.deleted_at is None:
            return None
        days = getattr(settings, "TRASH_RETENTION_DAYS", DEFAULT_TRASH_RETENTION_DAYS)
        return self.deleted_at + timedelta(days=days)

    def soft_delete(self):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])

    def restore(self):
        self.deleted_at = None
        self.save(update_fields=["deleted_at"])

    @classmethod
    def purge_stale(cls, cutoff, dry_run=False):
        """Hard-delete (or, if dry_run, just count) records trashed at or
        before `cutoff`. Default implementation for models with no special
        cascade needs. apps.content.Note overrides this - see
        apps.content.services for why a plain queryset delete isn't safe
        for a tree model.
        """
        qs = cls.objects.purgeable(cutoff)
        if dry_run:
            return qs.count()
        count, _ = qs.delete()
        return count


class ExpiryModel(models.Model):
    """Warranty / contract / reminder dates. No task fires on these yet
    (see plan: reminders are deliberately just fields for now) - they exist
    to filter and sort on."""

    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    remind_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        abstract = True
