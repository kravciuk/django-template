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
}
app.conf.task_routes = {
    "*.high_priority_task": {"queue": "high"},
}

app.conf.beat_schedule = {
    "update-geoip-database": {
        "task": "core.tasks.update_geoip_database",
        "schedule": crontab(hour=3, minute=0),
    },
    "backup-database": {
        "task": "core.tasks.backup_database",
        "schedule": crontab(hour=0, minute=0),
    },
    "cleanup-stale-drafts": {
        "task": "apps.content.tasks.cleanup_stale_drafts",
        "schedule": crontab(hour=2, minute=0),
    },
}


@app.task(bind=True, name="core.debug_task")
def debug_task(self):
    print(f"Request: {self.request!r}")
