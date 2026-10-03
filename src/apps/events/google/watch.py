"""Push notification channels (Calendar API events.watch).

With a live channel Google POSTs to webhook.py whenever the watched
calendar changes, and that queues the usual incremental sync - polling
drops to a rare fallback (sync.sync_interval). Channels can't be renewed:
before one expires a new one (new id) is opened and the old one stopped;
Google allows the overlap. Opening is checked at the end of every
successful sync (ensure_watch) - a watched account is synced at least every
GOOGLE_CALENDAR_WATCHED_SYNC_INTERVAL_MINUTES, well inside RENEW_MARGIN.

Only available with a public https SITE_URL and the constance switch on;
anything going wrong here leaves the account on plain polling.
"""
import logging
import random
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from constance import config
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from ..models import GoogleCalendarAccount
from .client import GoogleError

logger = logging.getLogger("apps")

RENEW_MARGIN = timedelta(days=1)
# Google's own maximum is about 7 days. A random TTL keeps channels opened
# together (e.g. on the day push is switched on) from expiring together.
TTL_MIN = timedelta(days=5)
TTL_MAX = timedelta(days=7)


def push_available():
    return bool(getattr(config, "GOOGLE_CALENDAR_PUSH_ENABLED", False) and settings.SITE_URL.startswith("https://"))


def webhook_url():
    return settings.SITE_URL + reverse("google_calendar_webhook")


def _wanted(account):
    return (
        push_available() and account.sync_enabled and account.calendar_id
        and account.status != GoogleCalendarAccount.Status.NEEDS_RECONNECT
    )


def _fresh(account):
    return (
        account.watch_channel_id and account.watch_calendar_id == account.calendar_id
        and account.watch_expires_at and account.watch_expires_at > timezone.now() + RENEW_MARGIN
    )


def ensure_watch(account, client):
    """Open, renew or stop the account's channel as needed - no Google call
    while the current one is fine."""
    if not _wanted(account):
        stop_watch(account, client)
        return
    if _fresh(account):
        return
    old_channel = (account.watch_channel_id, account.watch_resource_id)
    channel_id = uuid.uuid4().hex
    token = secrets.token_urlsafe(32)
    ttl = random.uniform(TTL_MIN.total_seconds(), TTL_MAX.total_seconds())
    try:
        channel = client.watch_events(
            account.calendar_id, channel_id=channel_id, token=token, address=webhook_url(), ttl_seconds=ttl,
        )
    except GoogleError as exc:
        # Stays on polling; the old channel (if any) works until it expires.
        logger.warning("Google Calendar push channel couldn't be opened", extra={"account": account.pk, "error": str(exc)})
        return
    expiration = channel.get("expiration")
    account.watch_channel_id = channel_id
    account.watch_resource_id = channel.get("resourceId", "")
    account.watch_token = token
    account.watch_calendar_id = account.calendar_id
    account.watch_expires_at = (
        datetime.fromtimestamp(int(expiration) / 1000, tz=UTC) if expiration else timezone.now() + timedelta(seconds=ttl)
    )
    account.save(update_fields=GoogleCalendarAccount.WATCH_FIELDS + ["updated_at"])
    if old_channel[0]:
        _stop_channel(account, client, *old_channel)


def stop_watch(account, client):
    """Forget the channel, then ask Google to stop it (best effort - an
    unknown channel's notifications are ignored by the webhook anyway)."""
    if not account.watch_channel_id:
        return
    channel = (account.watch_channel_id, account.watch_resource_id)
    account.clear_watch()
    account.save(update_fields=GoogleCalendarAccount.WATCH_FIELDS + ["updated_at"])
    _stop_channel(account, client, *channel)


def _stop_channel(account, client, channel_id, resource_id):
    try:
        client.stop_channel(channel_id, resource_id)
    except GoogleError as exc:
        logger.info("Google Calendar push channel couldn't be stopped", extra={"account": account.pk, "error": str(exc)})
