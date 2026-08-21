import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.dev")

app = Celery("core")

# Настройки Celery читаются из Django settings с префиксом CELERY_
# (CELERY_BROKER_URL, CELERY_RESULT_BACKEND и т.д., см. settings/base.py).
app.config_from_object("django.conf:settings", namespace="CELERY")

# Автоматическое обнаружение задач (tasks.py) во всех приложениях из
# INSTALLED_APPS, а также в самом core.
app.autodiscover_tasks()

# --- Очереди high/low ---
app.conf.task_default_queue = "low"
app.conf.task_queues = {
    "high": {"routing_key": "high"},
    "low": {"routing_key": "low"},
}
app.conf.task_routes = {
    # Задачи с именем, оканчивающимся на high_priority_task, идут в high,
    # остальные — в low (task_default_queue).
    "*.high_priority_task": {"queue": "high"},
}

# --- Celery Beat: периодические задачи ---
app.conf.beat_schedule = {
    "update-geoip-database": {
        "task": "core.tasks.update_geoip_database",
        "schedule": crontab(hour=3, minute=0),
    },
    "backup-database": {
        "task": "core.tasks.backup_database",
        "schedule": crontab(hour=0, minute=0),
    },
}


@app.task(bind=True, name="core.debug_task")
def debug_task(self):
    print(f"Request: {self.request!r}")
