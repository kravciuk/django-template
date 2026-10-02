from django.apps import AppConfig


class EventsConfig(AppConfig):
    """The /events/ calendar - a UI/API layer over apps.content.Note, like
    apps.documents. Stores nothing of its own (no models, no migrations):
    calendar placement lives on Note itself (starts_at/expires_at/all_day/
    color/recurrence/remind_minutes_before), quick notes are Notes of
    kind=EVENT under a hidden per-owner hub node (services.get_events_hub).
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.events"
    label = "events"

    def ready(self):
        from . import signals  # noqa: F401
