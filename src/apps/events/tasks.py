import logging

from celery import shared_task
from constance import config
from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext

from apps.content.models import Note
from apps.notifications.enums import NotificationKind
from apps.notifications.services import notify
from apps.users.formats import format_date, format_datetime

from .google import sync as google_sync
from .models import GoogleCalendarAccount
from .reminders import is_still_due, mark_delivered, owner_zone, refresh_reminder, reminder_offset
from .services import is_document

logger = logging.getLogger("celery")


def _reminder_payload(note):
    """Notification payload (title/body/url - see notifications.js) for the
    occurrence note.remind_at is about, with the time shown in the owner's
    own zone and display formats."""
    tz = owner_zone(note)
    event_at = timezone.localtime(note.remind_at + reminder_offset(note), tz)
    if note.all_day and not is_document(note):
        when = format_date(event_at.date(), user=note.owner)
    else:
        when = format_datetime(event_at, user=note.owner)
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


# --- Google Calendar sync (apps.events.google) ---
#
# Two queues (core/celery.py): `google_bulk` for the scheduled background
# work, `google` for syncs someone is waiting on (a push notification, "Sync
# now", a just-saved note) - so a backlog of routine syncs never delays them.

GOOGLE_QUEUE = "google"
GOOGLE_BULK_QUEUE = "google_bulk"
DEFAULT_DISPATCH_BATCH = 2000
# A queued account isn't queued again for this long (the task clears the
# mark when it starts) - a lagging queue doesn't fill up with duplicates.
QUEUED_TTL = 15 * 60
# A sync from a notification that found another sync running retries once,
# so a change that came in mid-run isn't left for the hourly fallback.
WEBHOOK_RETRY_DELAY = 60


def _active_google_accounts():
    return GoogleCalendarAccount.objects.filter(
        status=GoogleCalendarAccount.Status.ACTIVE, sync_enabled=True,
    ).exclude(calendar_id="")


def _queued_key(account_id):
    return f"gcal:queued:{account_id}"


def queue_account_sync(account_id, *, full=False, reconcile=False, interactive=False, from_webhook=False, countdown=None):
    """Queue one account's sync - on the interactive queue when someone is
    waiting for it."""
    sync_google_calendar_account.apply_async(
        (account_id,), {"full": full, "reconcile": reconcile, "from_webhook": from_webhook},
        queue=GOOGLE_QUEUE if interactive else GOOGLE_BULK_QUEUE, countdown=countdown,
    )


@shared_task(name="apps.events.tasks.sync_google_calendars")
def sync_google_calendars():
    """Beat task, every minute (see core/celery.py) - the one dispatcher of
    background syncs: queues accounts whose next_sync_at (or daily
    next_reconcile_at) has come, oldest first, at most
    GOOGLE_CALENDAR_DISPATCH_BATCH per run, skipping ones backing off after
    an error or still queued from an earlier run. The schedule itself is
    jittered per account (sync._record_success), so thousands of accounts
    reach Google spread out rather than all at once."""
    if not google_sync.sync_enabled():
        return 0
    now = timezone.now()
    batch = getattr(config, "GOOGLE_CALENDAR_DISPATCH_BATCH", DEFAULT_DISPATCH_BATCH)
    due = (
        _active_google_accounts()
        .filter(Q(retry_after__isnull=True) | Q(retry_after__lte=now))
        .filter(Q(next_sync_at__isnull=True) | Q(next_sync_at__lte=now) | Q(next_reconcile_at__lte=now))
        .order_by(F("next_sync_at").asc(nulls_first=True))
        .values_list("pk", "next_reconcile_at")[:batch]
    )
    queued = reconciles = 0
    for account_id, next_reconcile_at in due:
        if not cache.add(_queued_key(account_id), 1, QUEUED_TTL):
            continue
        reconcile = next_reconcile_at is not None and next_reconcile_at <= now
        queue_account_sync(account_id, reconcile=reconcile)
        queued += 1
        reconciles += reconcile
    if queued:
        logger.info("Google Calendar syncs queued", extra={"count": queued, "reconcile": reconciles})
    return queued


@shared_task(name="apps.events.tasks.sync_google_calendar_account")
def sync_google_calendar_account(account_id, full=False, reconcile=False, from_webhook=False):
    cache.delete(_queued_key(account_id))
    account = GoogleCalendarAccount.objects.select_related("user").filter(pk=account_id).first()
    if account is None:
        return "missing"
    result = google_sync.sync_account(account, full=full, reconcile=reconcile)
    if result is None and from_webhook and google_sync.is_running(account):
        queue_account_sync(account_id, interactive=True, countdown=WEBHOOK_RETRY_DELAY)
    return result.summary() if result else "skipped"


@shared_task(name="apps.events.tasks.push_notes_to_google")
def push_notes_to_google(note_ids):
    """Immediate push after notes were saved/trashed/restored here (queued
    by signals.queue_google_push)."""
    if not google_sync.sync_enabled():
        return 0
    owners = {}
    for note_id, owner_id in Note.objects.filter(pk__in=note_ids).values_list("pk", "owner_id"):
        owners.setdefault(owner_id, []).append(note_id)
    pushed = 0
    for account in _active_google_accounts().filter(user_id__in=owners).select_related("user"):
        if google_sync.push_notes(account, owners[account.user_id]) is not None:
            pushed += 1
    return pushed


@shared_task(name="apps.events.tasks.reconcile_google_calendars")
def reconcile_google_calendars():
    """Not scheduled - every account is reconciled about daily by the
    dispatcher (next_reconcile_at). Run by hand to make every account due
    for a reconcile now; the dispatcher then works through them in batches.
    A reconcile re-diffs every link, catching changes that don't bump
    Note.updated_at (time zone change, admin bulk trash/restore, constance
    reminder defaults)."""
    return _active_google_accounts().update(next_reconcile_at=timezone.now())
