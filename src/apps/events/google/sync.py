"""Two-way sync between a user's notes and one Google calendar.

One run (sync_account) = pull (Google -> notes) then push (notes -> Google),
under a per-account cache lock. Changes are found by comparing projections
(mapping.py) with GoogleEventLink.snapshot, the state both sides agreed on
at the last sync - a 3-way merge per field group:

- only Google changed  -> applied to the note (pull);
- only the note changed -> sent to Google (push, PATCH of those fields only);
- both changed          -> the later edit wins (Google's `updated` vs
                           note.updated_at); the other side is overwritten.

Documents are pushed read-only: anything changed or deleted in Google is put
back. Notes written by a pull run inside suppress_push(), so they don't
queue a push of what just came from Google.

Each account picks a direction (GoogleCalendarAccount.sync_direction):
- FROM_GOOGLE: no push at all; on a conflict Google always wins.
- TO_GOOGLE: Google is a read-only copy of this site - events created there
  aren't imported, and every linked event is treated like a document
  (changes and deletions in Google are put back).

Built for many accounts: a run that finds nothing new costs one events.list
call and a few queries - the push phase only runs when signals.py flagged
local changes (account.push_pending), the pull left something to send back
(result.needs_push), or on a reconcile. The next run is scheduled with
jitter (next_sync_at/next_reconcile_at), and a used-up shared request
budget (ratelimit.py -> QuotaPaused) just postpones the account.
"""
import logging
import random
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import timedelta

from constance import config
from django.core.cache import cache
from django.db.models import F, Q
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext

from apps.common.enums import ContentFormat, Visibility
from apps.content.enums import NoteKind
from apps.content.models import Note
from apps.notifications.enums import NotificationKind
from apps.notifications.services import notify
from apps.users.middleware import user_zoneinfo

from ..models import GoogleCalendarAccount, GoogleEventLink
from ..services import get_events_hub, is_document, syncable_notes
from . import mapping, watch
from .client import (
    BadRequest,
    CalendarClient,
    Conflict,
    GoogleAuthError,
    GoogleError,
    GoogleRateLimited,
    GoogleServerError,
    NotFound,
    QuotaPaused,
    SyncTokenExpired,
)

logger = logging.getLogger("apps")

LOCK_TIMEOUT = 15 * 60
MAX_BACKOFF_MINUTES = 60
DEFAULT_IMPORT_PAST_DAYS = 30
DEFAULT_MAX_WRITES_PER_RUN = 200
DEFAULT_SYNC_INTERVAL_MINUTES = 10
DEFAULT_WATCHED_SYNC_INTERVAL_MINUTES = 60
RECONCILE_INTERVAL = timedelta(days=1)
# Schedules are spread by +/-25% (Google's own advice), so accounts that
# connected together don't stay in lockstep.
SCHEDULE_JITTER = 0.25

_push_suppressed = ContextVar("gcal_push_suppressed", default=False)


@contextmanager
def suppress_push():
    token = _push_suppressed.set(True)
    try:
        yield
    finally:
        _push_suppressed.reset(token)


def push_suppressed():
    return _push_suppressed.get()


def sync_enabled():
    """Site-wide master switch. Which OAuth client an account syncs through
    is per account (credentials.for_account)."""
    return getattr(config, "GOOGLE_CALENDAR_SYNC_ENABLED", True)


def get_client(account):
    """Seam for tests (patched with a fake Google)."""
    return CalendarClient(account)


class SyncLocked(Exception):
    """Another sync of this account is running."""


class WriteBudgetExhausted(Exception):
    pass


@dataclass
class SyncResult:
    created: int = 0          # notes created from Google events
    updated: int = 0          # notes updated from Google
    trashed: int = 0          # notes trashed because deleted in Google
    inserted: int = 0         # events created in Google
    patched: int = 0          # events updated in Google
    deleted: int = 0          # events deleted in Google
    skipped: int = 0          # Google items not represented here (exceptions, special types)
    errors: list = field(default_factory=list)
    writes: int = 0
    # The pull left a link out of sync (read-only side put back, newer local
    # edit, purged note) - push even without account.push_pending.
    needs_push: bool = False

    @property
    def changed(self):
        return any((self.created, self.updated, self.trashed, self.inserted, self.patched, self.deleted))

    def summary(self):
        return (
            f"created={self.created} updated={self.updated} trashed={self.trashed} "
            f"inserted={self.inserted} patched={self.patched} deleted={self.deleted} "
            f"skipped={self.skipped} errors={len(self.errors)}"
        )


def import_cutoff():
    days = getattr(config, "GOOGLE_CALENDAR_IMPORT_PAST_DAYS", DEFAULT_IMPORT_PAST_DAYS)
    return timezone.now() - timedelta(days=days)


def _max_writes():
    return getattr(config, "GOOGLE_CALENDAR_MAX_WRITES_PER_RUN", DEFAULT_MAX_WRITES_PER_RUN)


def _lock_key(account):
    return f"gcal:sync:{account.pk}"


def is_running(account):
    return cache.get(_lock_key(account)) is not None


@contextmanager
def account_lock(account):
    key = _lock_key(account)
    if not cache.add(key, 1, LOCK_TIMEOUT):
        raise SyncLocked()
    try:
        yield
    finally:
        cache.delete(key)


# --- entry points ----------------------------------------------------------


def sync_account(account, *, full=False, reconcile=False, client=None):
    """Pull then push one account. Account-level failures (auth, rate limit,
    calendar gone) are recorded on the account instead of raised; returns
    the SyncResult, or None if another sync holds the lock."""
    if not account.calendar_id or account.status == GoogleCalendarAccount.Status.NEEDS_RECONNECT:
        return None
    reconcile = reconcile or full
    try:
        with account_lock(account):
            client = client or get_client(account)
            result = SyncResult()
            try:
                if full:
                    account.sync_token = ""
                # Pull also runs for TO_GOOGLE: it's how edits made in Google
                # are noticed (and then put back by the push).
                pull(account, client, result)
                if account.pushes and (reconcile or account.push_pending or result.needs_push):
                    _push_pending_changes(account, client, result, reconcile=reconcile)
            except WriteBudgetExhausted:
                pass
            except QuotaPaused as exc:
                _postpone(account, exc)
                result.errors.append(str(exc))
                return result
            except GoogleError as exc:
                record_failure(account, exc)
                result.errors.append(str(exc))
                return result
            watch.ensure_watch(account, client)
            _record_success(account, reconciled=reconcile)
            log = logger.info if result.changed or result.errors else logger.debug
            log("Google Calendar sync done", extra={"account": account.pk, "result": result.summary()})
            return result
    except SyncLocked:
        return None


def _push_pending_changes(account, client, result, *, reconcile):
    """The push phase with account.push_pending cleared up front: a note
    saved while it runs sets the flag again, and a push that doesn't finish
    (write budget, quota, error) leaves it set for the next run."""
    GoogleCalendarAccount.objects.filter(pk=account.pk).update(push_pending=False)
    account.push_pending = False
    finished = False
    try:
        push(account, client, result, reconcile=reconcile)
        finished = True
    finally:
        if not finished:
            GoogleCalendarAccount.objects.filter(pk=account.pk).update(push_pending=True)
            account.push_pending = True


def push_notes(account, note_ids, *, client=None):
    """Push just these notes now (after a save/trash/restore) - a cheap
    partial run; the next full run catches anything this one misses."""
    if not account.is_active or not account.sync_enabled or not account.calendar_id or not account.pushes:
        return None
    try:
        with account_lock(account):
            client = client or get_client(account)
            result = SyncResult()
            try:
                push(account, client, result, note_ids=note_ids)
            except WriteBudgetExhausted:
                pass
            except GoogleError as exc:
                record_failure(account, exc)
                result.errors.append(str(exc))
            return result
    except SyncLocked:
        return None


# --- account bookkeeping ---------------------------------------------------


def _jittered(delta):
    return delta * random.uniform(1 - SCHEDULE_JITTER, 1 + SCHEDULE_JITTER)


def sync_interval(account):
    """Time between background syncs: rare with a live push channel (the
    webhook brings changes), the regular polling interval otherwise."""
    if account.is_watched:
        minutes = getattr(config, "GOOGLE_CALENDAR_WATCHED_SYNC_INTERVAL_MINUTES", DEFAULT_WATCHED_SYNC_INTERVAL_MINUTES)
    else:
        minutes = getattr(config, "GOOGLE_CALENDAR_SYNC_INTERVAL_MINUTES", DEFAULT_SYNC_INTERVAL_MINUTES)
    return timedelta(minutes=minutes)


def _record_success(account, *, reconciled=False):
    now = timezone.now()
    account.last_synced_at = now
    account.consecutive_failures = 0
    account.retry_after = None
    account.last_error = ""
    if account.status == GoogleCalendarAccount.Status.ERROR:
        account.status = GoogleCalendarAccount.Status.ACTIVE
    account.next_sync_at = now + _jittered(sync_interval(account))
    if reconciled or account.next_reconcile_at is None:
        account.next_reconcile_at = now + _jittered(RECONCILE_INTERVAL)
    account.save(update_fields=[
        "last_synced_at", "consecutive_failures", "retry_after", "last_error", "status",
        "next_sync_at", "next_reconcile_at", "updated_at",
    ])


def _postpone(account, exc):
    """The OAuth client's shared request budget is used up: not this
    account's failure - just try again once the budget is back (spread a
    little, so the paused accounts don't all return in the same second)."""
    account.next_sync_at = timezone.now() + timedelta(seconds=exc.retry_after + random.uniform(0, 30))
    account.save(update_fields=["next_sync_at", "updated_at"])
    logger.info("Google Calendar sync postponed", extra={"account": account.pk, "error": str(exc)})


def record_failure(account, exc):
    now = timezone.now()
    account.last_error = str(exc)[:1000] or exc.__class__.__name__
    account.last_error_at = now
    update_fields = ["last_error", "last_error_at", "updated_at"]
    if isinstance(exc, GoogleAuthError):
        account.status = GoogleCalendarAccount.Status.NEEDS_RECONNECT
        account.clear_tokens()
        # Without tokens the push channel can't be stopped - it expires on its own.
        account.clear_watch()
        update_fields += ["status", "refresh_token_enc", "access_token_enc", "access_token_expires_at"]
        update_fields += GoogleCalendarAccount.WATCH_FIELDS
        _notify(account, gettext("Google Calendar disconnected"), gettext("Reconnect it to resume syncing."))
    elif isinstance(exc, NotFound):
        account.status = GoogleCalendarAccount.Status.ERROR
        update_fields.append("status")
        _notify(account, gettext("Google Calendar sync stopped"), gettext("The selected calendar is no longer available."))
    else:
        account.consecutive_failures += 1
        minutes = min(2 ** account.consecutive_failures, MAX_BACKOFF_MINUTES)
        if isinstance(exc, GoogleRateLimited) and exc.retry_after:
            minutes = max(minutes, exc.retry_after / 60)
        account.retry_after = now + timedelta(minutes=minutes)
        update_fields += ["consecutive_failures", "retry_after"]
    account.save(update_fields=update_fields)
    logger.warning("Google Calendar sync failed", extra={"account": account.pk, "error": account.last_error})


def _notify(account, title, body):
    notify(account.user, kind=NotificationKind.SYSTEM, payload={
        "title": title, "body": body, "url": reverse("events:google_settings"),
    })


def _count_write(result):
    if result.writes >= _max_writes():
        raise WriteBudgetExhausted()
    result.writes += 1


# --- pull: Google -> notes -------------------------------------------------


def pull(account, client, result):
    full = not account.sync_token
    time_min = import_cutoff() if full else None
    seen = set()
    page_token = None
    try:
        while True:
            page = client.list_events(
                account.calendar_id, sync_token=account.sync_token or None, time_min=time_min, page_token=page_token,
            )
            items = page.get("items", [])
            # One query per page, not per event (a full listing page holds
            # up to 2500 events).
            links = {
                link.event_id: link
                for link in account.links.filter(
                    calendar_id=account.calendar_id, event_id__in=[event["id"] for event in items],
                ).select_related("note")
            }
            for event in items:
                seen.add(event["id"])
                try:
                    _pull_event(account, client, event, result, links.get(event["id"]))
                except (BadRequest, NotFound, Conflict) as exc:
                    result.errors.append(f"{event.get('id')}: {exc}")
            page_token = page.get("nextPageToken")
            if not page_token:
                next_sync_token = page.get("nextSyncToken", "")
                break
    except SyncTokenExpired:
        if full:
            raise
        account.sync_token = ""
        return pull(account, client, result)

    if full:
        _check_unlisted_links(account, client, seen, result)
    account.sync_token = next_sync_token
    update_fields = ["sync_token", "updated_at"]
    if full:
        account.last_full_sync_at = timezone.now()
        update_fields.append("last_full_sync_at")
    account.save(update_fields=update_fields)


def _check_unlisted_links(account, client, seen, result):
    """A full listing only covers the import window - linked events missing
    from it are looked up one by one to tell "old" from "deleted"."""
    links = account.links.filter(calendar_id=account.calendar_id, state=GoogleEventLink.State.ACTIVE)
    for link in links.exclude(event_id__in=seen).select_related("note"):
        try:
            event = client.get_event(account.calendar_id, link.event_id)
        except NotFound:
            event = {"id": link.event_id, "status": "cancelled"}
        if event.get("status") == "cancelled":
            _remote_deleted(account, link, result)


def _pull_event(account, client, event, result, link):
    """`link`: the event's GoogleEventLink, if any (loaded per page by pull)."""
    if event.get("eventType", "default") != "default" or event.get("recurringEventId"):
        # Birthdays/out-of-office/focus time, and single-occurrence
        # exceptions of a series, have no counterpart here.
        result.skipped += 1
        return
    if link is not None and link.state == GoogleEventLink.State.DETACHED:
        return
    if event.get("status") == "cancelled":
        if link is not None:
            _remote_deleted(account, link, result)
        return
    if link is None:
        link = _relink(account, event)
    if link is None:
        if account.pulls:
            _import_event(account, event, result)
        else:
            result.skipped += 1
        return
    if link.etag and link.etag == event.get("etag"):
        return  # unchanged since our own write
    _merge_remote(account, link, event, result)


def _relink(account, event):
    """An event this site created earlier whose link was lost (reconnect,
    calendar switched back) - find its note by the id stored in the event."""
    public_id = mapping.linked_note_public_id(event)
    if not public_id:
        return None
    note = Note.objects.alive().filter(owner=account.user, public_id=public_id).first()
    if note is None or note.google_links.filter(account=account, state=GoogleEventLink.State.ACTIVE).exists():
        return None
    return GoogleEventLink.objects.create(
        account=account, note=note, note_public_id=note.public_id, calendar_id=account.calendar_id,
        event_id=event["id"], origin=GoogleEventLink.Origin.LOCAL, is_document=is_document(note),
        snapshot={},  # unknown base: both sides count as changed, the later edit wins
    )


def _event_ends_before(event, cutoff, tz):
    if event.get("recurrence"):
        return False
    when = mapping.event_when(event, tz)
    if when is None:
        return True
    if when["all_day"]:
        return when["end"] < timezone.localtime(cutoff, tz).date().isoformat()
    return parse_datetime(when["end"]) < cutoff


def _import_event(account, event, result):
    tz = owner_zone_for(account)
    if mapping.event_when(event, tz) is None or _event_ends_before(event, import_cutoff(), tz):
        return
    remote = mapping.project_event(event, tz)
    note = Note(
        owner=account.user, kind=NoteKind.EVENT, body_format=ContentFormat.PLAIN,
        visibility=Visibility.PRIVATE, is_draft=False, title="",
    )
    mapping.apply_projection(note, remote, tz)
    with suppress_push():
        note = Note.objects.add_child(get_events_hub(account.user), instance=note)
    GoogleEventLink.objects.create(
        account=account, note=note, note_public_id=note.public_id, calendar_id=account.calendar_id,
        event_id=event["id"], origin=GoogleEventLink.Origin.GOOGLE,
        remote_editable=_remote_editable(event), etag=event.get("etag", ""),
        google_updated=_google_updated(event), snapshot=mapping.project_note(note, tz),
        note_synced_at=note.updated_at,
    )
    result.created += 1


def _read_only_in_google(account, link):
    """Google's side of this link is never applied here - only put back."""
    return link.is_document or not account.pulls


def _remote_deleted(account, link, result):
    note = link.note
    if _read_only_in_google(account, link):
        result.needs_push = True  # the push puts the event back
    elif note is not None and note.deleted_at is None:
        with suppress_push():
            note.soft_delete()
        result.trashed += 1
    # Documents (and everything in TO_GOOGLE): dropping the link makes the
    # push phase put the event back.
    link.delete()


def _merge_remote(account, link, event, result):
    note = link.note
    if note is None:
        result.needs_push = True  # purged here - the push phase deletes the Google event
        return
    tz = owner_zone_for(account)
    remote = mapping.project_event(event, tz)
    local = mapping.project_note(note, tz)
    base = link.snapshot or {}
    remote_wins = _google_updated(event) is not None and _google_updated(event) > note.updated_at

    changes = {}
    if not _read_only_in_google(account, link):
        for key in mapping.PROJECTION_KEYS:
            if remote.get(key) == local.get(key):
                continue
            if key in base and remote.get(key) == base[key]:
                continue  # Google didn't change it
            local_changed = key not in base or local.get(key) != base[key]
            if local_changed and link.remote_editable and account.pushes and not remote_wins:
                continue  # our newer edit is pushed below
            if key == "description" and note.body_format != ContentFormat.PLAIN:
                continue  # rich text is edited here only; the push restores it
            if key == "when" and remote.get(key) is None:
                continue
            changes[key] = remote[key]

    if changes and mapping.apply_projection(note, changes, tz):
        with suppress_push():
            note.save()
        result.updated += 1

    # The snapshot becomes what Google has now: whatever still differs
    # locally (our newer edits, a document, a rich-text body) is pushed.
    link.snapshot = remote
    link.etag = event.get("etag", "")
    link.google_updated = _google_updated(event)
    in_sync = mapping.project_note(note, tz) == remote
    link.note_synced_at = note.updated_at if in_sync else None
    if not in_sync:
        result.needs_push = True
    link.last_error = ""
    link.save(update_fields=["snapshot", "etag", "google_updated", "note_synced_at", "last_error", "updated_at"])


def _remote_editable(event):
    return (event.get("organizer") or {}).get("self", True)


def _google_updated(event):
    return parse_datetime(event["updated"]) if event.get("updated") else None


def owner_zone_for(account):
    return user_zoneinfo(account.user) or timezone.get_default_timezone()


# --- push: notes -> Google -------------------------------------------------


def push(account, client, result, *, reconcile=False, note_ids=None):
    tz = owner_zone_for(account)
    eligible = syncable_notes(account.user, include_documents=account.push_documents)
    links = account.links.filter(calendar_id=account.calendar_id, state=GoogleEventLink.State.ACTIVE)
    if note_ids is not None:
        eligible = eligible.filter(pk__in=note_ids)
        links = links.filter(Q(note_id__in=note_ids) | Q(note__isnull=True))
    # Subqueries, not a Python set of every note id: the cost stays in the DB.
    eligible_pks = eligible.values("pk")

    # 1. Gone here (purged, trashed, no longer on the calendar) -> delete there.
    # exclude() on the nullable FK keeps the links whose note was purged.
    for link in links.exclude(note__in=eligible_pks):
        _push_delete(account, client, link, result)

    # 2. Changed here since the last sync -> PATCH the changed fields.
    dirty = links.filter(note__in=eligible_pks).select_related("note")
    if not reconcile:
        dirty = dirty.filter(Q(note_synced_at__isnull=True) | Q(note__updated_at__gt=F("note_synced_at")))
    for link in dirty:
        if link.remote_editable:
            _push_update(account, client, link, tz, result)

    # 3. New here (no link at all, inside the import window) -> insert.
    cutoff = import_cutoff()
    in_window = (
        ~Q(recurrence="") | Q(expires_at__gte=cutoff) | Q(expires_at__isnull=True, starts_at__gte=cutoff)
    )
    new_notes = eligible.filter(in_window).exclude(google_links__account=account).select_related("owner")
    for note in new_notes:
        _push_insert(account, client, note, tz, result)


def _push_delete(account, client, link, result):
    if link.remote_editable:
        _count_write(result)
        try:
            client.delete_event(link.calendar_id, link.event_id)
        except BadRequest as exc:
            # e.g. 403 on an event we may not delete - drop the link anyway.
            result.errors.append(f"{link.event_id}: {exc}")
        result.deleted += 1
    link.delete()


def _push_update(account, client, link, tz, result):
    note = link.note
    local = mapping.project_note(note, tz)
    base = link.snapshot or {}
    keys = [key for key in mapping.PROJECTION_KEYS if local.get(key) != base.get(key)]
    if not keys:
        link.note_synced_at = note.updated_at
        link.save(update_fields=["note_synced_at", "updated_at"])
        return
    _count_write(result)
    try:
        event = client.patch_event(link.calendar_id, link.event_id, mapping.event_body(note, tz, keys=keys, for_patch=True))
    except NotFound:
        link.delete()  # deleted in Google meanwhile - re-inserted by the next run
        return
    except BadRequest as exc:
        link.last_error = str(exc)[:1000]
        link.save(update_fields=["last_error", "updated_at"])
        result.errors.append(f"{link.event_id}: {exc}")
        return
    _store_pushed(link, event, note, tz)
    result.patched += 1


def _push_insert(account, client, note, tz, result):
    body = mapping.new_event_body(note, tz)
    _count_write(result)
    try:
        try:
            event = client.insert_event(account.calendar_id, body)
        except Conflict:
            # Our id already exists: an earlier insert whose link was lost, or
            # an event deleted in Google (ids stay reserved) - take it over.
            existing = client.get_event(account.calendar_id, body["id"])
            if mapping.linked_note_public_id(existing) != str(note.public_id):
                raise
            patch = {key: value for key, value in body.items() if key != "id"}
            patch["status"] = "confirmed"
            _count_write(result)
            event = client.patch_event(account.calendar_id, body["id"], patch)
    except (BadRequest, Conflict, NotFound) as exc:
        result.errors.append(f"{note.public_id}: {exc}")
        logger.info("Google Calendar insert failed", extra={"note": str(note.public_id), "error": str(exc)})
        return
    link = GoogleEventLink(
        account=account, note=note, note_public_id=note.public_id, calendar_id=account.calendar_id,
        event_id=event["id"], origin=GoogleEventLink.Origin.LOCAL, is_document=is_document(note),
    )
    _store_pushed(link, event, note, tz)
    result.inserted += 1


def _store_pushed(link, event, note, tz):
    link.snapshot = mapping.project_event(event, tz)
    link.etag = event.get("etag", "")
    link.google_updated = _google_updated(event)
    link.note_synced_at = note.updated_at
    link.last_error = ""
    link.save()


# --- account-level operations (settings page) -------------------------------


def switch_calendar(account, calendar_id, calendar_summary, *, client=None):
    """Point the account at another calendar: events this site created are
    removed from the old one (they're re-created in the new one), notes
    imported from it stay here but are no longer synced."""
    if calendar_id == account.calendar_id:
        return
    old_links = account.links.filter(calendar_id=account.calendar_id, state=GoogleEventLink.State.ACTIVE)
    if account.calendar_id and account.is_active:
        client = client or get_client(account)
        for link in old_links.filter(origin=GoogleEventLink.Origin.LOCAL):
            try:
                client.delete_event(link.calendar_id, link.event_id)
            except GoogleError as exc:
                logger.info("Google Calendar: couldn't remove event from the old calendar", extra={"error": str(exc)})
    old_links.filter(origin=GoogleEventLink.Origin.LOCAL).delete()
    old_links.update(state=GoogleEventLink.State.DETACHED)
    account.calendar_id = calendar_id
    account.calendar_summary = calendar_summary
    account.sync_token = ""
    account.push_pending = True  # everything goes into the new calendar
    account.save(update_fields=["calendar_id", "calendar_summary", "sync_token", "push_pending", "updated_at"])


def delete_created_events(account, *, client=None):
    """Remove every event this site created in the connected calendar
    (offered when disconnecting). Best effort."""
    client = client or get_client(account)
    links = account.links.filter(origin=GoogleEventLink.Origin.LOCAL, state=GoogleEventLink.State.ACTIVE)
    for link in links:
        try:
            client.delete_event(link.calendar_id, link.event_id)
        except GoogleError as exc:
            logger.info("Google Calendar: couldn't delete a created event", extra={"error": str(exc)})
            if isinstance(exc, (GoogleAuthError, GoogleRateLimited, GoogleServerError, QuotaPaused)):
                break
