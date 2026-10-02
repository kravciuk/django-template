import logging

from celery import shared_task
from django.db import transaction
from django.urls import reverse
from django.utils import formats, timezone
from django.utils.translation import gettext

from apps.content.models import Note
from apps.notifications.enums import NotificationKind
from apps.notifications.services import notify

from .reminders import is_still_due, mark_delivered, owner_zone, refresh_reminder, reminder_offset
from .services import is_document

logger = logging.getLogger("celery")


def _reminder_payload(note):
    """Notification payload (title/body/url - see notifications.js) for the
    occurrence note.remind_at is about, with the time shown in the owner's
    own zone."""
    tz = owner_zone(note)
    event_at = timezone.localtime(note.remind_at + reminder_offset(note), tz)
    if note.all_day and not is_document(note):
        when = formats.date_format(event_at.date(), "SHORT_DATE_FORMAT")
    else:
        when = formats.date_format(event_at, "SHORT_DATETIME_FORMAT")
    if is_document(note):
        body = gettext("Expires: %(when)s") % {"when": when}
        url = reverse("documents:detail", args=[note.public_id])
    else:
        body = gettext("Starts: %(when)s") % {"when": when}
        url = reverse("content:note_detail", args=[note.public_id])
    return {"title": note.title, "body": body, "url": url}


@shared_task(name="apps.events.tasks.send_due_reminders")
def send_due_reminders():
    """Beat task, every 5 minutes (see core/celery.py) - delivers every
    calendar reminder whose remind_at has come, as an in-app notification,
    then schedules that note's next one (recurring events)."""
    now = timezone.now()
    due = (
        Note.objects.alive()
        .filter(is_draft=False, remind_at__isnull=False, remind_at__lte=now)
        .select_related("owner")
        .order_by("remind_at")
    )
    sent = 0
    for note in due:
        if not is_still_due(note):
            # Settings changed since remind_at was computed - reschedule
            # instead of delivering a reminder the user no longer wants.
            refresh_reminder(note, now)
            continue
        with transaction.atomic():
            notify(note.owner, kind=NotificationKind.SYSTEM, payload=_reminder_payload(note), target=note)
            mark_delivered(note, now)
        sent += 1
    logger.info("send_due_reminders: sent %d reminder(s)", sent, extra={"count": sent})
    return sent
