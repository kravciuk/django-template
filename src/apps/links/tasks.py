import logging

from celery import shared_task

from . import services

logger = logging.getLogger("celery")


@shared_task(name="apps.links.tasks.refetch_missing_favicons")
def refetch_missing_favicons():
    """Daily beat task (see core/celery.py) - retries the favicon lookup for
    links that still have none (site was down, blocked us, or only got an
    icon source fetch_favicon learned to use later).
    """
    checked, fixed = services.refetch_missing_favicons()
    logger.info(
        "refetch_missing_favicons: fetched %d of %d missing favicon(s)",
        fixed,
        checked,
        extra={"checked": checked, "fixed": fixed},
    )
    return fixed
