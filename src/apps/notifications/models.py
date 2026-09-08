from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimeStampedModel

from .enums import NotificationKind


class Notification(TimeStampedModel):
    """A single item in a user's notification inbox, delivered live over
    WebSocket (see apps.notifications.consumers/realtime) and readable later
    through the REST API (see apps.notifications.api). `sender` is null for
    system- and task-generated notifications; `target` is an optional
    generic link back to whatever the notification is about (a task, a
    comment, ...). Full user-to-user conversations/threads are a separate,
    later feature - this model only covers single delivered notifications.
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("recipient"),
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_notifications",
        verbose_name=_("sender"),
        help_text=_("Empty means a system- or task-generated notification."),
    )
    kind = models.CharField(
        _("kind"), max_length=16, choices=NotificationKind.choices, db_index=True,
    )
    # Free-form text + extra data, as opposed to a fixed set of columns -
    # different kinds carry different shapes (e.g. a task notification may
    # carry a task id and status, a message just a body).
    payload = models.JSONField(_("payload"), default=dict, blank=True)

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True, blank=True)
    object_id = models.PositiveBigIntegerField(null=True, blank=True)
    target = GenericForeignKey("content_type", "object_id")

    is_read = models.BooleanField(_("is read"), default=False, db_index=True)
    read_at = models.DateTimeField(_("read at"), null=True, blank=True)

    class Meta:
        verbose_name = _("notification")
        verbose_name_plural = _("notifications")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "created_at"]),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} -> {self.recipient_id}"

    def mark_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])
