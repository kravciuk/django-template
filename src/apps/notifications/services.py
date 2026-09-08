"""Single entry point other apps/tasks use to create a notification. Keeps
callers ignorant of the delivery mechanism (DB row + WebSocket push)."""

from django.contrib.contenttypes.models import ContentType
from django.db import transaction

from .models import Notification
from .realtime import push_notification


def notify(recipient, *, kind, payload, sender=None, target=None):
    """Create a Notification for `recipient` and push it over WebSocket once
    the surrounding transaction (if any) actually commits.

    `target`, if given, is any model instance the notification is about
    (e.g. a task, a comment) - stored as a generic relation so the client can
    deep-link to it.
    """
    notification = Notification.objects.create(
        recipient=recipient,
        sender=sender,
        kind=kind,
        payload=payload,
        content_type=ContentType.objects.get_for_model(target) if target is not None else None,
        object_id=target.pk if target is not None else None,
    )
    transaction.on_commit(lambda: push_notification(notification))
    return notification
