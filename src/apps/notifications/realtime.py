"""Push side of the notification pipeline: takes a persisted Notification
and fans it out over the Channels/Redis layer to whichever WebSocket
connections belong to its recipient (see apps.notifications.consumers)."""

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def group_name_for(user_id):
    return f"notifications.user.{user_id}"


def push_notification(notification):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        # No CHANNEL_LAYERS configured (shouldn't happen outside a
        # misconfigured environment) - the notification still exists in the
        # DB and is reachable through the REST API, so just skip the push.
        return

    # Imported here, not at module load time, to avoid a serializers -> models
    # -> realtime -> serializers import cycle.
    from .serializers import NotificationSerializer

    async_to_sync(channel_layer.group_send)(
        group_name_for(notification.recipient_id),
        {"type": "notification.push", "payload": NotificationSerializer(notification).data},
    )
