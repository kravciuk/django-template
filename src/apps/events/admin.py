from django.contrib import admin, messages
from django.utils import timezone
from django.utils.text import Truncator
from django.utils.translation import ngettext
from django.utils.translation import gettext_lazy as _

from .models import GoogleCalendarAccount, GoogleEventLink, GoogleOAuthClient
from .tasks import queue_account_sync


class PushChannelFilter(admin.SimpleListFilter):
    title = _("push channel")
    parameter_name = "push"

    def lookups(self, request, model_admin):
        return [("live", _("Live")), ("none", _("None or expired"))]

    def queryset(self, request, queryset):
        live = {"watch_expires_at__gt": timezone.now()}
        if self.value() == "live":
            return queryset.filter(**live)
        if self.value() == "none":
            return queryset.exclude(**live)
        return queryset


@admin.register(GoogleCalendarAccount)
class GoogleCalendarAccountAdmin(admin.ModelAdmin):
    list_display = (
        "user", "google_email", "calendar_summary", "status", "sync_direction", "sync_enabled", "last_synced_at",
        "error_short",
    )
    list_filter = ("status", "sync_direction", "sync_enabled", PushChannelFilter)
    search_fields = ("user__username", "user__email", "google_email", "calendar_summary")
    # Tokens (and the push channel's secret) never leave the DB in readable
    # form, not even to the admin.
    exclude = ("refresh_token_enc", "access_token_enc", "watch_token", "watch_resource_id")
    readonly_fields = (
        "user", "google_email", "granted_scopes", "oauth_client_id", "calendar_id", "calendar_summary", "status",
        "access_token_expires_at", "sync_token", "last_synced_at", "last_full_sync_at", "next_sync_at",
        "next_reconcile_at", "push_pending", "retry_after", "consecutive_failures", "last_error", "last_error_at",
        "watch_channel_id", "watch_calendar_id", "watch_expires_at", "created_at", "updated_at",
    )
    actions = ["sync_now", "force_full_resync"]

    def has_add_permission(self, request):
        return False  # accounts are created by the OAuth flow only

    def save_model(self, request, obj, form, change):
        # A different set of notes to push - the next sync must not skip it.
        if {"push_documents", "sync_direction"} & set(form.changed_data):
            obj.push_pending = True
        super().save_model(request, obj, form, change)

    @admin.display(description=_("Last error"))
    def error_short(self, obj):
        return Truncator(obj.last_error).chars(60)

    @admin.action(description=_("Sync now"))
    def sync_now(self, request, queryset):
        for account in queryset:
            queue_account_sync(account.pk, interactive=True)
        count = queryset.count()
        self.message_user(request, ngettext(
            "Sync queued for %(count)d account.", "Sync queued for %(count)d accounts.", count,
        ) % {"count": count}, messages.SUCCESS)

    @admin.action(description=_("Force a full resync"))
    def force_full_resync(self, request, queryset):
        queryset.update(sync_token="")
        for account in queryset:
            queue_account_sync(account.pk, full=True, interactive=True)
        count = queryset.count()
        self.message_user(request, ngettext(
            "Full resync queued for %(count)d account.", "Full resync queued for %(count)d accounts.", count,
        ) % {"count": count}, messages.SUCCESS)


@admin.register(GoogleOAuthClient)
class GoogleOAuthClientAdmin(admin.ModelAdmin):
    list_display = ("user", "client_id", "updated_at")
    search_fields = ("user__username", "user__email", "client_id")
    # The secret never leaves the DB in readable form, not even to the admin.
    exclude = ("client_secret_enc",)
    readonly_fields = ("user", "client_id", "created_at", "updated_at")

    def has_add_permission(self, request):
        return False  # entered by the user on the Google Calendar settings page


@admin.register(GoogleEventLink)
class GoogleEventLinkAdmin(admin.ModelAdmin):
    list_display = ("note_public_id", "note", "account", "origin", "state", "is_document", "google_updated", "updated_at")
    list_filter = ("state", "origin", "is_document")
    search_fields = ("event_id", "note__title", "note_public_id")
    raw_id_fields = ("note",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # maintained by the sync; delete a link to force a re-link
