# Гарантирует загрузку приложения Celery при старте Django, чтобы
# @shared_task из core/tasks.py и apps/*/tasks.py были привязаны к нему.
from core.celery import app as celery_app  # noqa: E402,F401

__all__ = ("celery_app",)
