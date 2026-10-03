"""Shared request budget per OAuth client.

Google counts Calendar API quota per Google Cloud project, i.e. per OAuth
client - every account connected through the site-wide client shares one
budget (10,000 requests/minute), a user's own client has its own. Each
request takes a slot from a per-minute counter in Redis; once the budget
(constance GOOGLE_CALENDAR_MAX_REQUESTS_PER_MINUTE, set below Google's limit)
is used up, or Google itself reported a project-level limit (pause()), every
request through that client is refused until the window passes - the client
raises client.QuotaPaused then, which the sync doesn't count as the
account's failure.
"""
import time

from constance import config
from django.core.cache import cache

DEFAULT_MAX_REQUESTS_PER_MINUTE = 8000
DEFAULT_PAUSE_SECONDS = 60
WINDOW_SECONDS = 60


def _limit():
    return getattr(config, "GOOGLE_CALENDAR_MAX_REQUESTS_PER_MINUTE", DEFAULT_MAX_REQUESTS_PER_MINUTE)


def _pause_key(client_key):
    return f"gcal:paused:{client_key}"


def acquire(client_key):
    """Take one request slot for this OAuth client: 0 if granted, otherwise
    the seconds to wait."""
    now = time.time()
    paused_until = cache.get(_pause_key(client_key))
    if paused_until and paused_until > now:
        return paused_until - now

    window = int(now // WINDOW_SECONDS)
    key = f"gcal:quota:{client_key}:{window}"
    cache.add(key, 0, WINDOW_SECONDS * 2)
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add() and incr()
        cache.add(key, 1, WINDOW_SECONDS * 2)
        count = 1
    if count > _limit():
        return WINDOW_SECONDS - now % WINDOW_SECONDS
    return 0


def pause(client_key, seconds=None):
    """Stop every request through this client for a while - Google said the
    project is over its quota."""
    seconds = max(seconds or DEFAULT_PAUSE_SECONDS, 1)
    cache.set(_pause_key(client_key), time.time() + seconds, int(seconds) + 1)


def paused(client_key):
    paused_until = cache.get(_pause_key(client_key))
    return bool(paused_until and paused_until > time.time())
