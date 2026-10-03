from django.core.validators import RegexValidator

CONSTANCE_BACKEND = "constance.backends.database.DatabaseBackend"

# These used to be plain env-driven Django settings (base.py) - moved here so
# they're editable at runtime from /admin/constance/config/ without a
# redeploy. Application code reads them via `from constance import config`
# (see apps.attachments.validators, apps.common.models, apps.comments.models,
# apps.content.tasks/views, apps.notifications.tasks,
# apps.common.management.commands.purge_trash).
#
# DATA_UPLOAD_MAX_MEMORY_SIZE/FILE_UPLOAD_MAX_MEMORY_SIZE (base.py) are real
# Django framework settings read by the multipart parser outside of any
# request-scoped hook, so they stay static and are sized off the *defaults*
# below at startup - raising ATTACHMENTS_MAX_UPLOAD_SIZE here at runtime does
# not itself raise that hard cap; a redeploy is still needed for that.

# Extra constance field types - "color" renders a native color picker and
# rejects anything that isn't #rrggbb (used by the EVENTS_*_COLOR keys).
CONSTANCE_ADDITIONAL_FIELDS = {
    "color": [
        "django.forms.CharField",
        {
            "widget": "django.forms.TextInput",
            "widget_kwargs": {"attrs": {"type": "color"}},
            "validators": [RegexValidator(r"^#[0-9a-fA-F]{6}$", "Enter a color as #rrggbb.")],
        },
    ],
}

CONSTANCE_CONFIG = {
    "ATTACHMENTS_MAX_UPLOAD_SIZE": (
        25 * 1024 * 1024,
        "Max size (bytes) of a single uploaded attachment file.",
        int,
    ),
    "ATTACHMENTS_ALLOWED_EXTENSIONS": (
        "",
        "Comma-separated allowed upload extensions, e.g. 'jpg,png,pdf' (empty = no restriction).",
        str,
    ),
    "ATTACHMENTS_MAX_FILES_PER_UPLOAD": (
        10,
        "Max number of files accepted in a single upload request.",
        int,
    ),
    "TRASH_RETENTION_DAYS": (
        30,
        "Days a soft-deleted row stays in trash before purge_trash hard-deletes it.",
        int,
    ),
    "DRAFT_RETENTION_DAYS": (
        7,
        "Days an untouched draft note survives before cleanup_stale_drafts trashes it.",
        int,
    ),
    "COMMENTS_MAX_DEPTH": (
        5,
        "Max nesting depth allowed for threaded comments.",
        int,
    ),
    "NOTIFICATIONS_RETENTION_DAYS": (
        90,
        "Days a read notification is kept before cleanup_old_notifications hard-deletes it.",
        int,
    ),
    "ACCOUNT_ALLOW_SIGNUP": (
        False,
        "Whether self-registration (/accounts/signup/) is open. Keep off until "
        "docs/future/multi-user-migration.md's prerequisites (SSRF in the link "
        "favicon fetcher, the global tag autocomplete, apps.sharing) are closed.",
        bool,
    ),
    "EVENTS_NOTE_COLOR": (
        "#3a3f44",
        "Default /events/ calendar color for notes (dark gray). A note's own color overrides it.",
        "color",
    ),
    "EVENTS_DOCUMENT_COLOR": (
        "#5c3d2e",
        "Default /events/ calendar color for documents (dark brown).",
        "color",
    ),
    "EVENTS_DOCUMENT_REMIND_DAYS": (
        14,
        "Days before a document's expiry date to send a reminder, unless the document sets "
        "its own reminder (0 = no default reminder).",
        int,
    ),
    "GOOGLE_CALENDAR_SYNC_ENABLED": (
        True,
        "Master switch for Google Calendar sync (apps.events.google). Off = no background "
        "syncs or pushes; connected accounts are kept.",
        bool,
    ),
    "GOOGLE_CALENDAR_SYNC_INTERVAL_MINUTES": (
        10,
        "Minutes between background syncs of each connected Google calendar without a live push "
        "channel (jittered by +/-25%).",
        int,
    ),
    "GOOGLE_CALENDAR_WATCHED_SYNC_INTERVAL_MINUTES": (
        60,
        "Minutes between fallback syncs of calendars that have a live push channel - changes "
        "arrive through the webhook, this only catches lost notifications.",
        int,
    ),
    "GOOGLE_CALENDAR_PUSH_ENABLED": (
        False,
        "Ask Google to notify this site about calendar changes (events.watch) instead of relying "
        "on polling. Needs a public https SITE_URL.",
        bool,
    ),
    "GOOGLE_CALENDAR_IMPORT_PAST_DAYS": (
        30,
        "How far back (days) events are imported from / sent to Google on a full sync. "
        "Older one-off events are left alone on both sides.",
        int,
    ),
    "GOOGLE_CALENDAR_MAX_WRITES_PER_RUN": (
        200,
        "Cap on Google API writes per account per sync run; the rest waits for the next run.",
        int,
    ),
    "GOOGLE_CALENDAR_MAX_REQUESTS_PER_MINUTE": (
        8000,
        "Cap on Google Calendar API requests per minute per OAuth client (Google's own limit is "
        "10,000 per project); above it syncs pause until the next minute.",
        int,
    ),
    "GOOGLE_CALENDAR_DISPATCH_BATCH": (
        2000,
        "Max accounts queued for a background sync per minute (oldest first).",
        int,
    ),
}

CONSTANCE_CONFIG_FIELDSETS = {
    "Attachments": (
        "ATTACHMENTS_MAX_UPLOAD_SIZE",
        "ATTACHMENTS_ALLOWED_EXTENSIONS",
        "ATTACHMENTS_MAX_FILES_PER_UPLOAD",
    ),
    "Retention": (
        "TRASH_RETENTION_DAYS",
        "DRAFT_RETENTION_DAYS",
        "NOTIFICATIONS_RETENTION_DAYS",
    ),
    "Comments": ("COMMENTS_MAX_DEPTH",),
    "Auth": ("ACCOUNT_ALLOW_SIGNUP",),
    "Events": (
        "EVENTS_NOTE_COLOR",
        "EVENTS_DOCUMENT_COLOR",
        "EVENTS_DOCUMENT_REMIND_DAYS",
    ),
    "Google Calendar": (
        "GOOGLE_CALENDAR_SYNC_ENABLED",
        "GOOGLE_CALENDAR_PUSH_ENABLED",
        "GOOGLE_CALENDAR_SYNC_INTERVAL_MINUTES",
        "GOOGLE_CALENDAR_WATCHED_SYNC_INTERVAL_MINUTES",
        "GOOGLE_CALENDAR_IMPORT_PAST_DAYS",
        "GOOGLE_CALENDAR_MAX_WRITES_PER_RUN",
        "GOOGLE_CALENDAR_MAX_REQUESTS_PER_MINUTE",
        "GOOGLE_CALENDAR_DISPATCH_BATCH",
    ),
}
