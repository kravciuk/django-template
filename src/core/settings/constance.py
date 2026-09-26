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
}
