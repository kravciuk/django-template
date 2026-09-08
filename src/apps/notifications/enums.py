from django.db import models
from django.utils.translation import gettext_lazy as _


class NotificationKind(models.TextChoices):
    """Facebook-bell-style categories: an announcement from the system
    itself, a status update about a background task, or a message authored
    by another user. `sender` on Notification is what actually distinguishes
    system/task (no sender) from a user-authored one, not this field alone -
    `kind` just drives icon/grouping in the client."""

    SYSTEM = "system", _("System")
    TASK = "task", _("Task")
    MESSAGE = "message", _("Message")
