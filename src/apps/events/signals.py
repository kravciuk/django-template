from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.content.models import Note
from apps.content.signals import notes_restored, notes_trashed

from .google.sync import push_suppressed, sync_enabled
from .models import GoogleCalendarAccount
from .reminders import refresh_reminder
from .tasks import push_notes_to_google

# A save queues a Google push this many seconds later; further saves of the
# same note meanwhile (autosave) ride along with that one push.
GOOGLE_PUSH_DELAY = 30


@receiver(post_save, sender=Note, dispatch_uid="events_refresh_note_reminder")
def refresh_note_reminder(sender, instance, raw=False, **kwargs):
    # Keeps Note.remind_at in sync with whatever was just saved (dates,
    # recurrence, reminder offset, draft flag) without apps.content having
    # to know about reminders. Fixture loading (raw) is left alone.
    if raw:
        return
    refresh_reminder(instance)


@receiver(post_save, sender=Note, dispatch_uid="events_google_push_on_save")
def queue_google_push_on_save(sender, instance, raw=False, **kwargs):
    if raw:
        return
    queue_google_push([instance.pk], owner_ids=[instance.owner_id])


@receiver(notes_trashed, dispatch_uid="events_google_push_on_trash")
@receiver(notes_restored, dispatch_uid="events_google_push_on_restore")
def queue_google_push_on_trash_or_restore(sender, pks, **kwargs):
    queue_google_push(pks)


@receiver(post_delete, sender=Note, dispatch_uid="events_google_push_on_purge")
def mark_google_push_on_purge(sender, instance, **kwargs):
    # A purged note leaves its link behind (note=NULL); the next push
    # deletes the Google event.
    if not push_suppressed():
        _mark_push_pending([instance.owner_id])


def _pushing_accounts():
    return GoogleCalendarAccount.objects.exclude(sync_direction=GoogleCalendarAccount.SyncDirection.FROM_GOOGLE)


def _mark_push_pending(owner_ids):
    """Tell the next sync of these owners' accounts there's something to
    push - without it a sync skips the push phase. Marked for every account
    (also disabled ones), so changes made meanwhile go out once it's back."""
    _pushing_accounts().filter(user_id__in=owner_ids, push_pending=False).update(push_pending=True)


def queue_google_push(note_ids, owner_ids=None):
    """Flag these notes' owners' accounts for a push, and queue an immediate
    one if they're connected. Skipped for writes made by the sync itself
    (suppress_push); the immediate push also where no worker would consume
    it (GOOGLE_CALENDAR_ENQUEUE_ON_SAVE off, e.g. dev) - the next sync then
    pushes the flagged changes."""
    if not note_ids or push_suppressed():
        return
    if owner_ids is None:
        owner_ids = list(Note.objects.filter(pk__in=note_ids).values_list("owner_id", flat=True).distinct())
    _mark_push_pending(owner_ids)
    if not settings.GOOGLE_CALENDAR_ENQUEUE_ON_SAVE or not sync_enabled():
        return
    accounts = _pushing_accounts().filter(status=GoogleCalendarAccount.Status.ACTIVE, sync_enabled=True)
    if not accounts.filter(user_id__in=owner_ids).exists():
        return
    queued = [pk for pk in note_ids if cache.add(f"gcal:push:{pk}", 1, GOOGLE_PUSH_DELAY)]
    if not queued:
        return
    transaction.on_commit(lambda: push_notes_to_google.apply_async((queued,), countdown=GOOGLE_PUSH_DELAY))
