"""Google Calendar connection pages: settings (incl. the user's own OAuth
client), OAuth connect/callback, disconnect, "Sync now". Available to every
signed-in user: without the site-wide OAuth client
(settings.GOOGLE_OAUTH_CLIENT_ID/SECRET) a user can still connect through
their own one (credentials.py).

The callback lives outside i18n_patterns (core/urls.py) so the redirect URI
registered in Google never carries a language prefix; the language the user
connected from is carried through the session instead.
"""
import logging
import secrets
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import translation
from django.utils.crypto import constant_time_compare
from django.utils.translation import gettext, ngettext
from django.views import View

from ..forms import GoogleCalendarSettingsForm, GoogleOAuthClientForm
from ..models import GoogleCalendarAccount, GoogleOAuthClient
from ..tasks import queue_account_sync
from . import client as google
from . import credentials, sync, watch
from .crypto import TokenDecryptError

logger = logging.getLogger("apps")

SESSION_KEY = "google_calendar_oauth"
STATE_MAX_AGE = 10 * 60
OAUTH_FORM_PREFIX = "oauth"


def redirect_uri(request):
    return settings.GOOGLE_OAUTH_REDIRECT_URI or request.build_absolute_uri(reverse("google_oauth_callback"))


def run_sync(request, account, *, full=False):
    """Inline in dev (no Celery worker), queued otherwise."""
    if settings.GOOGLE_CALENDAR_SYNC_INLINE:
        result = sync.sync_account(account, full=full)
        account.refresh_from_db()
        if result is None:
            messages.info(request, gettext("A sync is already running."))
        elif result.errors and account.last_error:
            messages.error(request, gettext("Sync failed: %(error)s") % {"error": account.last_error})
        else:
            received = result.created + result.updated + result.trashed
            sent = result.inserted + result.patched + result.deleted
            messages.success(request, ngettext(
                "Synced: %(received)d change from Google, %(sent)d sent.",
                "Synced: %(received)d changes from Google, %(sent)d sent.",
                received,
            ) % {"received": received, "sent": sent})
        return
    queue_account_sync(account.pk, full=full, interactive=True)
    messages.info(request, gettext("Sync started - changes appear within a minute or two."))


class GoogleSettingsPageMixin(LoginRequiredMixin):
    """Renders the settings page - also from GoogleOAuthClientView, to show
    its form errors."""

    template_name = "events/google_settings.html"

    def _calendars(self, request, account):
        try:
            return sync.get_client(account).list_calendars()
        except google.GoogleError as exc:
            if isinstance(exc, google.GoogleAuthError):
                sync.record_failure(account, exc)
            messages.error(request, gettext("Couldn't load your Google calendars: %(error)s") % {"error": exc})
            return []

    def render_page(self, request, *, account=None, form=None, oauth_form=None):
        if account is None:
            account = GoogleCalendarAccount.objects.filter(user=request.user).first()
        if form is None and account is not None and account.is_active:
            form = GoogleCalendarSettingsForm(calendars=self._calendars(request, account), initial={
                "calendar_id": account.calendar_id,
                "sync_direction": account.sync_direction,
                "sync_enabled": account.sync_enabled,
                "push_documents": account.push_documents,
            })
        own_client = GoogleOAuthClient.objects.filter(user=request.user).first()
        if oauth_form is None:
            oauth_form = GoogleOAuthClientForm(
                current=own_client, prefix=OAUTH_FORM_PREFIX,
                initial={"client_id": own_client.client_id} if own_client else None,
            )
        return render(request, self.template_name, {
            "account": account,
            "form": form,
            "oauth_form": oauth_form,
            "own_client": own_client,
            "oauth_client": credentials.for_user(request.user),
            "redirect_uri": redirect_uri(request),
            "required_scopes": google.REQUIRED_SCOPES,
            "poll_minutes": int(sync.sync_interval(account).total_seconds() // 60) if account else None,
        })


class GoogleCalendarSettingsView(GoogleSettingsPageMixin, View):
    def get(self, request):
        return self.render_page(request)

    def post(self, request):
        account = get_object_or_404(GoogleCalendarAccount, user=request.user, status=GoogleCalendarAccount.Status.ACTIVE)
        form = GoogleCalendarSettingsForm(request.POST, calendars=self._calendars(request, account))
        if not form.is_valid():
            return self.render_page(request, account=account, form=form)
        calendar_changed = form.cleaned_data["calendar_id"] != account.calendar_id
        if calendar_changed:
            sync.switch_calendar(account, form.cleaned_data["calendar_id"], form.calendar_summary())
        documents_changed = form.cleaned_data["push_documents"] != account.push_documents
        direction_changed = form.cleaned_data["sync_direction"] != account.sync_direction
        if account.sync_enabled and not form.cleaned_data["sync_enabled"]:
            watch.stop_watch(account, sync.get_client(account))
        account.sync_direction = form.cleaned_data["sync_direction"]
        account.sync_enabled = form.cleaned_data["sync_enabled"]
        account.push_documents = form.cleaned_data["push_documents"]
        # Documents in or out: a different set of notes to push.
        account.push_pending = account.push_pending or documents_changed
        account.save(update_fields=["sync_direction", "sync_enabled", "push_documents", "push_pending", "updated_at"])
        messages.success(request, gettext("Google Calendar settings saved."))
        if account.sync_enabled and (calendar_changed or documents_changed or direction_changed):
            # A new direction re-diffs everything: what one side skipped so
            # far (imports, pushes) is due now.
            run_sync(request, account, full=calendar_changed or direction_changed)
        return redirect("events:google_settings")


class GoogleOAuthClientView(GoogleSettingsPageMixin, View):
    """Save or remove the user's own OAuth client. A connection made through
    a client that no longer applies has to be made again."""

    http_method_names = ["post"]

    def post(self, request):
        own_client = GoogleOAuthClient.objects.filter(user=request.user).first()
        if request.POST.get("action") == "remove":
            if own_client is not None:
                own_client.delete()
                messages.success(request, gettext("Your own Google application was removed."))
        else:
            form = GoogleOAuthClientForm(request.POST, current=own_client, prefix=OAUTH_FORM_PREFIX)
            if not form.is_valid():
                return self.render_page(request, oauth_form=form)
            if own_client is None:
                own_client = GoogleOAuthClient(user=request.user)
            own_client.client_id = form.cleaned_data["client_id"]
            if form.cleaned_data["client_secret"]:
                own_client.set_client_secret(form.cleaned_data["client_secret"])
            own_client.save()
            messages.success(request, gettext("Your Google application was saved."))
        self._drop_stale_connection(request)
        return redirect("events:google_settings")

    def _drop_stale_connection(self, request):
        account = GoogleCalendarAccount.objects.filter(user=request.user).select_related("user").first()
        if account is None or not account.refresh_token_enc or credentials.for_account(account) is not None:
            return
        try:
            google.revoke_token(account.get_refresh_token())
        except TokenDecryptError:
            pass
        account.clear_tokens()
        # The channel was opened through the old client - it can't be stopped
        # any more and just expires.
        account.clear_watch()
        account.status = GoogleCalendarAccount.Status.NEEDS_RECONNECT
        account.save(update_fields=[
            "refresh_token_enc", "access_token_enc", "access_token_expires_at", "status", "updated_at",
            *GoogleCalendarAccount.WATCH_FIELDS,
        ])
        messages.warning(request, gettext("Reconnect Google Calendar to sync through the new application."))


class GoogleConnectView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        oauth_client = credentials.for_user(request.user)
        if oauth_client is None:
            messages.error(request, gettext("Add your Google application (client ID and secret) first."))
            return redirect("events:google_settings")
        verifier, challenge = google.make_pkce_pair()
        state = secrets.token_urlsafe(32)
        request.session[SESSION_KEY] = {
            "state": state,
            "verifier": verifier,
            "client_id": oauth_client.client_id,
            "next": reverse("events:google_settings"),
            "language": translation.get_language(),
            "ts": time.time(),
        }
        return redirect(google.authorization_url(
            client_id=oauth_client.client_id, state=state, code_challenge=challenge,
            redirect_uri=redirect_uri(request), login_hint=request.user.email,
        ))


class GoogleCallbackView(LoginRequiredMixin, View):
    def get(self, request):
        data = request.session.pop(SESSION_KEY, None) or {}
        with translation.override(data.get("language") or settings.LANGUAGE_CODE):
            return self._handle(request, data)

    def _handle(self, request, data):
        next_url = data.get("next") or reverse("events:google_settings")
        state_ok = (
            data.get("state")
            and constant_time_compare(request.GET.get("state", ""), data["state"])
            and time.time() - data.get("ts", 0) <= STATE_MAX_AGE
        )
        if not state_ok:
            messages.error(request, gettext("The Google sign-in expired or didn't match. Try connecting again."))
            return redirect(next_url)
        if request.GET.get("error") or not request.GET.get("code"):
            messages.warning(request, gettext("Google Calendar wasn't connected."))
            return redirect(next_url)
        oauth_client = credentials.by_id(request.user, data.get("client_id", ""))
        if oauth_client is None:
            messages.error(request, gettext("Your Google application changed during the sign-in. Try connecting again."))
            return redirect(next_url)
        try:
            tokens = google.exchange_code(
                request.GET["code"], oauth_client=oauth_client, code_verifier=data["verifier"],
                redirect_uri=redirect_uri(request),
            )
        except google.GoogleError as exc:
            logger.warning("Google OAuth code exchange failed", extra={"error": str(exc)})
            messages.error(request, gettext("Google didn't accept the sign-in. Try connecting again."))
            return redirect(next_url)

        granted = set(tokens.get("scope", "").split())
        if not set(google.REQUIRED_SCOPES) <= granted or not tokens.get("refresh_token"):
            google.revoke_token(tokens.get("refresh_token") or tokens.get("access_token"))
            messages.error(request, gettext(
                "Google Calendar needs access to both your calendar list and your events - "
                "allow both on Google's consent screen and try again."
            ))
            return redirect(next_url)

        account, _created = GoogleCalendarAccount.objects.get_or_create(user=request.user)
        account.set_refresh_token(tokens["refresh_token"])
        account.set_access_token(tokens["access_token"], google.token_expiry(tokens.get("expires_in")))
        account.granted_scopes = " ".join(sorted(granted))
        account.oauth_client_id = oauth_client.client_id
        account.status = GoogleCalendarAccount.Status.ACTIVE
        account.last_error = ""
        account.consecutive_failures = 0
        account.retry_after = None
        account.save()

        try:
            calendars = sync.get_client(account).list_calendars()
        except google.GoogleError:
            calendars = []
        primary = next((item for item in calendars if item.get("primary")), None)
        if primary is not None:
            account.google_email = primary["id"]
        known = {item["id"]: item for item in calendars}
        if (not account.calendar_id or account.calendar_id not in known) and primary is not None:
            account.calendar_id = primary["id"]
            account.calendar_summary = primary.get("summaryOverride") or primary.get("summary") or primary["id"]
            account.sync_token = ""
        account.save()

        messages.success(request, gettext("Google Calendar connected."))
        if account.calendar_id and account.sync_enabled:
            run_sync(request, account, full=True)
        return redirect(next_url)


class GoogleDisconnectView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        account = get_object_or_404(GoogleCalendarAccount, user=request.user)
        if account.is_active:
            # Before the grant is revoked - stopping needs it.
            watch.stop_watch(account, sync.get_client(account))
        if request.POST.get("delete_created") and account.is_active:
            sync.delete_created_events(account)
        try:
            google.revoke_token(account.get_refresh_token())
        except TokenDecryptError:
            pass
        account.delete()
        messages.success(request, gettext("Google Calendar disconnected."))
        return redirect("events:google_settings")


class GoogleSyncNowView(LoginRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request):
        account = get_object_or_404(GoogleCalendarAccount, user=request.user, status=GoogleCalendarAccount.Status.ACTIVE)
        run_sync(request, account, full=bool(request.POST.get("full")))
        return redirect("events:google_settings")
