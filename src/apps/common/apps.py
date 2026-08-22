from django.apps import AppConfig


class CommonConfig(AppConfig):
    """Abstract-only package: base classes, enums and the purge_trash
    command shared by every other apps.* package. No models of its own, so
    no migrations."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.common"
    label = "common"
