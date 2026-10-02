from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.content.models import Note

from .reminders import refresh_reminder


@receiver(post_save, sender=Note, dispatch_uid="events_refresh_note_reminder")
def refresh_note_reminder(sender, instance, raw=False, **kwargs):
    # Keeps Note.remind_at in sync with whatever was just saved (dates,
    # recurrence, reminder offset, draft flag) without apps.content having
    # to know about reminders. Fixture loading (raw) is left alone.
    if raw:
        return
    refresh_reminder(instance)
