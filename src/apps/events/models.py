"""Google Calendar sync state (apps.events.google). Calendar placement
itself still lives on apps.content.Note - these models only remember which
Google calendar a user connected and which Google event mirrors which note.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.common.models import TimeStampedModel

from .google.crypto import decrypt, encrypt


class GoogleOAuthClient(TimeStampedModel):
    """A user's own OAuth client (from their own Google Cloud project), used
    instead of the site-wide one from settings (google/credentials.py). Kept
    apart from GoogleCalendarAccount: it's entered before the first connect
    and survives a disconnect. The secret is stored encrypted - use the
    get_/set_ helpers."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="google_oauth_client",
        verbose_name=_("User"),
    )
    client_id = models.CharField(_("Client ID"), max_length=255)
    client_secret_enc = models.TextField(blank=True)

    class Meta:
        verbose_name = _("Google OAuth client")
        verbose_name_plural = _("Google OAuth clients")

    def __str__(self):
        return f"{self.user} -> {self.client_id}"

    def get_client_secret(self):
        return decrypt(self.client_secret_enc)

    def set_client_secret(self, secret):
        self.client_secret_enc = encrypt(secret)


class GoogleCalendarAccount(TimeStampedModel):
    """One connected Google account (and the one calendar picked in it) per
    user. Tokens are stored encrypted (google/crypto.py) - use the
    get_/set_ helpers, never the *_enc fields directly."""

    class Status(models.TextChoices):
        ACTIVE = "active", _("Active")
        NEEDS_RECONNECT = "needs_reconnect", _("Needs reconnecting")
        ERROR = "error", _("Error")

    class SyncDirection(models.TextChoices):
        BOTH = "both", _("Both ways")
        FROM_GOOGLE = "from_google", _("Only from Google to this site")
        TO_GOOGLE = "to_google", _("Only from this site to Google")

    WATCH_FIELDS = ["watch_channel_id", "watch_resource_id", "watch_token", "watch_calendar_id", "watch_expires_at"]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="google_calendar",
        verbose_name=_("User"),
    )
    google_email = models.CharField(_("Google account"), max_length=254, blank=True)
    refresh_token_enc = models.TextField(blank=True)
    access_token_enc = models.TextField(blank=True)
    access_token_expires_at = models.DateTimeField(null=True, blank=True)
    granted_scopes = models.TextField(_("Granted scopes"), blank=True)
    # The OAuth client the tokens were issued to - refreshing them must go
    # through the same one. "" = the site-wide client from settings.
    oauth_client_id = models.CharField(_("OAuth client ID"), max_length=255, blank=True)
    calendar_id = models.CharField(_("Calendar"), max_length=255, blank=True)
    calendar_summary = models.CharField(_("Calendar name"), max_length=255, blank=True)
    status = models.CharField(_("Status"), max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    sync_enabled = models.BooleanField(_("Sync enabled"), default=True)
    push_documents = models.BooleanField(_("Include document expiry dates"), default=True)
    sync_direction = models.CharField(
        _("Sync direction"), max_length=20, choices=SyncDirection.choices, default=SyncDirection.BOTH,
    )
    # Google's nextSyncToken for incremental listing; "" = a full sync is due.
    sync_token = models.TextField(blank=True)
    last_synced_at = models.DateTimeField(_("Last synced"), null=True, blank=True)
    last_full_sync_at = models.DateTimeField(_("Last full sync"), null=True, blank=True)
    # Background schedule (tasks.sync_google_calendars), each one jittered so
    # thousands of accounts don't all hit Google at the same moment.
    next_sync_at = models.DateTimeField(_("Next sync"), null=True, blank=True, db_index=True)
    next_reconcile_at = models.DateTimeField(_("Next reconcile"), null=True, blank=True, db_index=True)
    # Something changed here since the last push (set by signals.py) - a run
    # without it skips the push phase entirely.
    push_pending = models.BooleanField(_("Push pending"), default=True)
    # Backoff after rate limits / server errors - background syncs skip the
    # account until then.
    retry_after = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveSmallIntegerField(default=0)
    last_error = models.TextField(_("Last error"), blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    # Push notification channel (google/watch.py): Google POSTs to the webhook
    # whenever the watched calendar changes.
    watch_channel_id = models.CharField(_("Push channel"), max_length=64, blank=True, db_index=True)
    watch_resource_id = models.CharField(max_length=255, blank=True)
    watch_token = models.CharField(max_length=64, blank=True)
    watch_calendar_id = models.CharField(_("Push channel calendar"), max_length=255, blank=True)
    watch_expires_at = models.DateTimeField(_("Push channel expires"), null=True, blank=True)

    class Meta:
        verbose_name = _("Google Calendar account")
        verbose_name_plural = _("Google Calendar accounts")

    def __str__(self):
        return f"{self.user} -> {self.google_email or '?'} / {self.calendar_summary or self.calendar_id or '?'}"

    @property
    def is_active(self):
        return self.status == self.Status.ACTIVE

    @property
    def is_watched(self):
        """A live push channel delivers changes - polling can be rare."""
        return bool(self.watch_channel_id and self.watch_expires_at and self.watch_expires_at > timezone.now())

    def clear_watch(self):
        self.watch_channel_id = ""
        self.watch_resource_id = ""
        self.watch_token = ""
        self.watch_calendar_id = ""
        self.watch_expires_at = None

    @property
    def pulls(self):
        """Changes made in Google are applied here."""
        return self.sync_direction in (self.SyncDirection.BOTH, self.SyncDirection.FROM_GOOGLE)

    @property
    def pushes(self):
        """Notes are written to Google."""
        return self.sync_direction in (self.SyncDirection.BOTH, self.SyncDirection.TO_GOOGLE)

    def get_refresh_token(self):
        return decrypt(self.refresh_token_enc)

    def set_refresh_token(self, token):
        self.refresh_token_enc = encrypt(token)

    def get_access_token(self):
        return decrypt(self.access_token_enc)

    def set_access_token(self, token, expires_at):
        self.access_token_enc = encrypt(token)
        self.access_token_expires_at = expires_at

    def clear_tokens(self):
        self.refresh_token_enc = ""
        self.access_token_enc = ""
        self.access_token_expires_at = None


class GoogleEventLink(TimeStampedModel):
    """Which Google event mirrors which note. Kept outside Note.json_data:
    every full Note.save() rewrites json_data from the copy it loaded, and a
    link must outlive a purged note (note=NULL) until the next sync deletes
    the Google event too."""

    class Origin(models.TextChoices):
        LOCAL = "local", _("Created here")
        GOOGLE = "google", _("Imported from Google")

    class State(models.TextChoices):
        ACTIVE = "active", _("Active")
        # After switching calendars: the imported note stays here but is no
        # longer synced anywhere.
        DETACHED = "detached", _("Detached")

    account = models.ForeignKey(
        GoogleCalendarAccount, on_delete=models.CASCADE, related_name="links", verbose_name=_("Account"),
    )
    note = models.ForeignKey(
        "content.Note", on_delete=models.SET_NULL, null=True, blank=True, related_name="google_links",
        verbose_name=_("Note"),
    )
    note_public_id = models.UUIDField(_("Note ID"), db_index=True)
    calendar_id = models.CharField(_("Calendar"), max_length=255)
    event_id = models.CharField(_("Google event ID"), max_length=1024)
    origin = models.CharField(_("Origin"), max_length=10, choices=Origin.choices)
    state = models.CharField(_("State"), max_length=10, choices=State.choices, default=State.ACTIVE, db_index=True)
    is_document = models.BooleanField(_("Document"), default=False)
    # False for invitations where the user isn't the organizer: pulled
    # only, never pushed.
    remote_editable = models.BooleanField(default=True)
    etag = models.CharField(max_length=255, blank=True)
    google_updated = models.DateTimeField(null=True, blank=True)
    # The common projection (google/mapping.py) both sides agreed on at the
    # last sync - the base of the 3-way merge.
    snapshot = models.JSONField(default=dict, blank=True)
    # note.updated_at when `snapshot` was taken - a newer updated_at means
    # the note may have changed since.
    note_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(_("Last error"), blank=True)

    class Meta:
        verbose_name = _("Google event link")
        verbose_name_plural = _("Google event links")
        constraints = [
            models.UniqueConstraint(fields=["account", "calendar_id", "event_id"], name="events_gcal_link_event_uniq"),
            models.UniqueConstraint(
                fields=["account", "note"], condition=Q(note__isnull=False, state="active"),
                name="events_gcal_link_active_note_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.note_public_id} <-> {self.event_id}"
