"""Receiver of Google Calendar push notifications (see watch.py).

The project's only public, CSRF-exempt endpoint, so it trusts nothing in
the request: the channel id must belong to an active account, and the token
(a secret only Google and we know) and resource id must match. A
notification carries no data - it only says "this calendar changed" - so
all it can do is queue the usual authorized incremental sync, debounced per
account. Anything that doesn't check out gets the same empty 204 as a valid
notification (nothing to learn from the response, and Google doesn't retry
2xx).
"""
import logging

from django.core.cache import cache
from django.http import HttpResponse
from django.utils.crypto import constant_time_compare
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from ..models import GoogleCalendarAccount
from ..tasks import queue_account_sync
from .sync import sync_enabled

logger = logging.getLogger("apps")

# Notifications arriving within this window (a burst of edits, our own
# writes echoing back) share one sync.
DEBOUNCE_SECONDS = 10
# Lets a burst settle before the sync lists the changes.
SYNC_DELAY_SECONDS = 5
CHANGE_STATES = {"exists", "not_exists"}


@method_decorator(csrf_exempt, name="dispatch")
class GoogleCalendarWebhookView(View):
    http_method_names = ["post"]

    def post(self, request):
        channel_id = request.headers.get("X-Goog-Channel-ID", "")
        state = request.headers.get("X-Goog-Resource-State", "")
        # The master switch stops these background syncs too; channels just
        # run out (or get stopped by the first sync once it's back on).
        account = self._account(request, channel_id) if sync_enabled() else None
        if account is None:
            logger.info("Google Calendar notification ignored", extra={"channel": channel_id[:64], "state": state[:32]})
        elif state in CHANGE_STATES and cache.add(f"gcal:webhook:{account.pk}", 1, DEBOUNCE_SECONDS):
            queue_account_sync(account.pk, interactive=True, from_webhook=True, countdown=SYNC_DELAY_SECONDS)
        # "sync" (sent once when a channel opens) needs nothing but the 2xx.
        return HttpResponse(status=204)

    def _account(self, request, channel_id):
        if not channel_id:
            return None
        account = (
            GoogleCalendarAccount.objects.filter(
                watch_channel_id=channel_id, status=GoogleCalendarAccount.Status.ACTIVE, sync_enabled=True,
            )
            .only("pk", "watch_token", "watch_resource_id")
            .first()
        )
        if account is None:
            return None
        token_ok = constant_time_compare(request.headers.get("X-Goog-Channel-Token", ""), account.watch_token)
        resource_ok = constant_time_compare(request.headers.get("X-Goog-Resource-ID", ""), account.watch_resource_id)
        return account if token_ok and resource_ok else None
