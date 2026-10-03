"""Thin HTTP layer over Google's OAuth 2.0 and Calendar v3 REST APIs, on
plain `requests` (same as apps.links) - only the handful of endpoints the
sync needs, so no google-api-python-client.

Errors are mapped onto the exception classes below; callers (sync.py)
decide what's fatal for an account and what only affects one event.
Request/response bodies are never logged - they carry tokens.
"""
import base64
import hashlib
import logging
import secrets
from datetime import timedelta
from urllib.parse import quote, urlencode

import requests
from django.conf import settings
from django.utils import timezone

from . import credentials, ratelimit
from .crypto import TokenDecryptError

logger = logging.getLogger("apps")

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API_BASE = "https://www.googleapis.com/calendar/v3"

# The narrowest pair that lets the user pick a calendar and fully manage
# events in calendars they own.
SCOPE_CALENDAR_LIST = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
SCOPE_EVENTS = "https://www.googleapis.com/auth/calendar.events.owned"
REQUIRED_SCOPES = (SCOPE_CALENDAR_LIST, SCOPE_EVENTS)

TIMEOUT = 15
# Refresh the access token this long before Google says it expires.
TOKEN_EXPIRY_MARGIN = timedelta(seconds=60)
RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded"}
# Limits of the whole Google Cloud project (Developer Console quotas): every
# account on that OAuth client is paused, not just this one. The rest
# (rateLimitExceeded, quotaExceeded) are per user/calendar - that account
# backs off alone.
PROJECT_LIMIT_PAUSE = {"userRateLimitExceeded": 60, "dailyLimitExceeded": 60 * 60}


class GoogleError(Exception):
    def __init__(self, message="", status=None):
        super().__init__(message)
        self.status = status


class GoogleAuthError(GoogleError):
    """The grant is gone (revoked, expired, invalid_grant) - the user must reconnect."""


class GoogleRateLimited(GoogleError):
    def __init__(self, message="", status=None, retry_after=None):
        super().__init__(message, status)
        self.retry_after = retry_after


class QuotaPaused(GoogleError):
    """The OAuth client's shared request budget is used up, or Google said
    its project is over quota (ratelimit.py) - every account on it waits, so
    it's not this account's failure."""

    def __init__(self, message="", status=None, retry_after=0):
        super().__init__(message, status)
        self.retry_after = retry_after


class GoogleServerError(GoogleError):
    """5xx or a network failure - transient, retry later."""


class SyncTokenExpired(GoogleError):
    """410 on an incremental list - drop the sync token and list everything."""


class NotFound(GoogleError):
    pass


class Conflict(GoogleError):
    """409 - e.g. inserting an event id that already exists."""


class BadRequest(GoogleError):
    """4xx about one request's content (bad rule, forbidden on that event...)."""


# --- OAuth -----------------------------------------------------------------


def make_pkce_pair():
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorization_url(*, client_id, state, code_challenge, redirect_uri, login_hint=""):
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(REQUIRED_SCOPES),
        # offline + consent: always hand out a refresh token, also on reconnect.
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URL}?{urlencode(params)}"


def _token_request(data, oauth_client):
    try:
        response = requests.post(TOKEN_URL, data={
            "client_id": oauth_client.client_id,
            "client_secret": oauth_client.client_secret,
            **data,
        }, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise GoogleServerError(f"Token endpoint unreachable: {exc.__class__.__name__}") from exc
    if response.status_code >= 500:
        raise GoogleServerError("Token endpoint error", response.status_code)
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if response.status_code != 200:
        error = payload.get("error", "")
        if error in ("invalid_grant", "unauthorized_client", "invalid_client"):
            raise GoogleAuthError(f"OAuth token request rejected: {error}", response.status_code)
        raise BadRequest(f"OAuth token request failed: {error or response.status_code}", response.status_code)
    return payload


def exchange_code(code, *, oauth_client, code_verifier, redirect_uri):
    """{access_token, expires_in, refresh_token, scope, ...} for an auth code."""
    return _token_request({
        "grant_type": "authorization_code",
        "code": code,
        "code_verifier": code_verifier,
        "redirect_uri": redirect_uri,
    }, oauth_client)


def refresh_access_token(refresh_token, oauth_client):
    return _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token}, oauth_client)


def revoke_token(token):
    """Best effort - a token that's already invalid is fine too."""
    if not token:
        return False
    try:
        response = requests.post(REVOKE_URL, data={"token": token}, timeout=TIMEOUT)
    except requests.RequestException:
        logger.info("Google token revoke failed (network)")
        return False
    return response.status_code == 200


def token_expiry(expires_in):
    return timezone.now() + timedelta(seconds=int(expires_in or 3600)) - TOKEN_EXPIRY_MARGIN


# --- Calendar API ----------------------------------------------------------


def _error_reason(response):
    try:
        errors = response.json().get("error", {}).get("errors") or []
    except (ValueError, AttributeError):
        return ""
    return errors[0].get("reason", "") if errors else ""


def _retry_after(response):
    try:
        return int(response.headers.get("Retry-After", ""))
    except ValueError:
        return None


class CalendarClient:
    """Calendar v3 calls on behalf of one GoogleCalendarAccount; refreshes
    and persists its access token as needed."""

    def __init__(self, account):
        self.account = account

    def _quota_key(self):
        """Which request budget this account spends (ratelimit.py) - its OAuth
        client, known without loading or decrypting anything."""
        return self.account.oauth_client_id or settings.GOOGLE_OAUTH_CLIENT_ID or "site"

    # -- auth --

    def _access_token(self, force_refresh=False):
        """Stored tokens or the OAuth client that can't be used any more
        (encryption key dropped, the user replaced their own client) end up
        as GoogleAuthError - the account needs reconnecting."""
        try:
            return self._valid_access_token(force_refresh)
        except TokenDecryptError as exc:
            raise GoogleAuthError("Stored Google tokens can't be decrypted") from exc

    def _valid_access_token(self, force_refresh):
        account = self.account
        expires_at = account.access_token_expires_at
        if not force_refresh and account.access_token_enc and expires_at and expires_at > timezone.now():
            return account.get_access_token()
        refresh_token = account.get_refresh_token()
        if not refresh_token:
            raise GoogleAuthError("No refresh token stored")
        oauth_client = credentials.for_account(account)
        if oauth_client is None:
            raise GoogleAuthError("The OAuth client this connection was made with is no longer configured")
        payload = refresh_access_token(refresh_token, oauth_client)
        account.set_access_token(payload["access_token"], token_expiry(payload.get("expires_in")))
        update_fields = ["access_token_enc", "access_token_expires_at", "updated_at"]
        if payload.get("refresh_token"):
            account.set_refresh_token(payload["refresh_token"])
            update_fields.append("refresh_token_enc")
        account.save(update_fields=update_fields)
        return payload["access_token"]

    def _request(self, method, path, *, params=None, json=None, _retried=False):
        headers = {"Authorization": f"Bearer {self._access_token(force_refresh=_retried)}"}
        wait = ratelimit.acquire(self._quota_key())
        if wait:
            raise QuotaPaused(f"Google Calendar request budget used up - retry in {wait:.0f} s", retry_after=wait)
        try:
            response = requests.request(
                method, f"{API_BASE}{path}", params=params, json=json, headers=headers, timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            raise GoogleServerError(f"Google Calendar unreachable: {exc.__class__.__name__}") from exc

        status = response.status_code
        if status == 401:
            if not _retried:
                return self._request(method, path, params=params, json=json, _retried=True)
            raise GoogleAuthError("Unauthorized after a token refresh", status)
        reason = _error_reason(response) if status in (403, 429) else ""
        if reason in PROJECT_LIMIT_PAUSE:
            seconds = max(_retry_after(response) or 0, PROJECT_LIMIT_PAUSE[reason])
            ratelimit.pause(self._quota_key(), seconds)
            raise QuotaPaused(f"Google project quota exceeded ({reason})", status, seconds)
        if status == 429 or (status == 403 and reason in RATE_LIMIT_REASONS):
            raise GoogleRateLimited("Rate limited", status, _retry_after(response))
        if status >= 500:
            raise GoogleServerError("Google Calendar server error", status)
        if status == 404:
            raise NotFound("Not found", status)
        if status == 409:
            raise Conflict("Conflict", status)
        if status == 410:
            raise SyncTokenExpired("Gone", status)
        if status >= 400:
            raise BadRequest(f"Request rejected ({_error_reason(response) or status})", status)
        if status == 204 or not response.content:
            return {}
        return response.json()

    @staticmethod
    def _calendar_path(calendar_id):
        return f"/calendars/{quote(calendar_id, safe='')}/events"

    # -- endpoints --

    def list_calendars(self):
        """Calendars the user owns (the only ones calendar.events.owned can
        write to)."""
        items, page_token = [], None
        while True:
            params = {"minAccessRole": "owner", "maxResults": 250}
            if page_token:
                params["pageToken"] = page_token
            page = self._request("GET", "/users/me/calendarList", params=params)
            items.extend(page.get("items", []))
            page_token = page.get("nextPageToken")
            if not page_token:
                return items

    def list_events(self, calendar_id, *, sync_token=None, time_min=None, page_token=None):
        """One page of events.list. Incremental (sync_token) and full
        (time_min) listings must not mix parameters - Google rejects that."""
        params = {"showDeleted": "true", "singleEvents": "false", "maxResults": 2500}
        if sync_token:
            params["syncToken"] = sync_token
        elif time_min is not None:
            params["timeMin"] = time_min.isoformat()
        if page_token:
            params["pageToken"] = page_token
        return self._request("GET", self._calendar_path(calendar_id), params=params)

    def get_event(self, calendar_id, event_id):
        return self._request("GET", f"{self._calendar_path(calendar_id)}/{quote(event_id, safe='')}")

    def insert_event(self, calendar_id, body):
        return self._request("POST", self._calendar_path(calendar_id), json=body)

    def patch_event(self, calendar_id, event_id, body):
        return self._request("PATCH", f"{self._calendar_path(calendar_id)}/{quote(event_id, safe='')}", json=body)

    def delete_event(self, calendar_id, event_id):
        """Already gone (404/410) counts as deleted."""
        try:
            self._request("DELETE", f"{self._calendar_path(calendar_id)}/{quote(event_id, safe='')}")
        except (NotFound, SyncTokenExpired):
            pass

    def watch_events(self, calendar_id, *, channel_id, token, address, ttl_seconds):
        """Open a push channel: Google POSTs to `address` whenever an event in
        the calendar changes. {id, resourceId, expiration (ms), ...}"""
        return self._request("POST", f"{self._calendar_path(calendar_id)}/watch", json={
            "id": channel_id,
            "type": "web_hook",
            "address": address,
            "token": token,
            "params": {"ttl": str(int(ttl_seconds))},
        })

    def stop_channel(self, channel_id, resource_id):
        """Already stopped or expired (404) counts as stopped."""
        try:
            self._request("POST", "/channels/stop", json={"id": channel_id, "resourceId": resource_id})
        except NotFound:
            pass
