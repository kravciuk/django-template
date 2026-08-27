import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .services import soft_delete_stale_drafts

logger = logging.getLogger("celery")

DEFAULT_DRAFT_RETENTION_DAYS = 7


@shared_task(name="apps.content.tasks.cleanup_stale_drafts")
def cleanup_stale_drafts():
    """Daily beat task (see core/celery.py) - trashes notes autosave created
    and that were abandoned without ever being explicitly saved.
    """
    retention_days = getattr(settings, "DRAFT_RETENTION_DAYS", DEFAULT_DRAFT_RETENTION_DAYS)
    cutoff = timezone.now() - timedelta(days=retention_days)
    count = soft_delete_stale_drafts(cutoff)
    logger.info("cleanup_stale_drafts: trashed %d abandoned draft(s)", count, extra={"count": count})
    return count
