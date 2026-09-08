import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .models import Notification

logger = logging.getLogger("celery")

DEFAULT_NOTIFICATIONS_RETENTION_DAYS = 90


@shared_task(name="apps.notifications.tasks.cleanup_old_notifications")
def cleanup_old_notifications():
    """Daily beat task (see core/celery.py) - hard-deletes read notifications
    older than NOTIFICATIONS_RETENTION_DAYS. Unread notifications are kept
    regardless of age; the user hasn't seen them yet.
    """
    retention_days = getattr(
        settings, "NOTIFICATIONS_RETENTION_DAYS", DEFAULT_NOTIFICATIONS_RETENTION_DAYS
    )
    cutoff = timezone.now() - timedelta(days=retention_days)
    count, _ = Notification.objects.filter(is_read=True, created_at__lte=cutoff).delete()
    logger.info("cleanup_old_notifications: deleted %d notification(s)", count, extra={"count": count})
    return count
