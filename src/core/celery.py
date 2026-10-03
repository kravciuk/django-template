import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.dev")

app = Celery("core")

app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.task_default_queue = "low"
app.conf.task_queues = {
    "high": {"routing_key": "high"},
    "low": {"routing_key": "low"},
    # Google Calendar sync (apps.events.tasks): its own workers, so it never
    # delays reminders/cleanup - `google` for syncs someone waits on (push
    # notification, "Sync now", a just-saved note), `google_bulk` for the
    # scheduled background syncs.
    "google": {"routing_key": "google"},
    "google_bulk": {"routing_key": "google_bulk"},
}
app.conf.task_routes = {
    "*.high_priority_task": {"queue": "high"},
    "apps.events.tasks.push_notes_to_google": {"queue": "google"},
    "apps.events.tasks.sync_google_calendar*": {"queue": "google_bulk"},
    "apps.events.tasks.reconcile_google_calendars": {"queue": "google_bulk"},
}

app.conf.beat_schedule = {
    "update-geoip-database": {
        "task": "core.tasks.update_geoip_database",
        "schedule": crontab(hour=3, minute=0),
    },
    "cleanup-stale-drafts": {
        "task": "apps.content.tasks.cleanup_stale_drafts",
        "schedule": crontab(hour=2, minute=0),
    },
    "cleanup-old-notifications": {
        "task": "apps.notifications.tasks.cleanup_old_notifications",
        "schedule": crontab(hour=4, minute=0),
    },
    "send-due-event-reminders": {
        "task": "apps.events.tasks.send_due_reminders",
        "schedule": crontab(minute="*/5"),
    },
    # The one dispatcher of background Google Calendar syncs: queues accounts
    # whose own (jittered) next_sync_at / daily next_reconcile_at has come.
    "sync-google-calendars": {
        "task": "apps.events.tasks.sync_google_calendars",
        "schedule": crontab(minute="*"),
    },
    "refetch-missing-favicons": {
        "task": "apps.links.tasks.refetch_missing_favicons",
        "schedule": crontab(hour=5, minute=0),
    },
}


@app.task(bind=True, name="core.debug_task")
def debug_task(self):
    print(f"Request: {self.request!r}")
