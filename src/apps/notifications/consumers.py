from channels.generic.websocket import AsyncJsonWebsocketConsumer

from .realtime import group_name_for


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    """Push-only channel: the server sends notification events as they're
    created (see apps.notifications.realtime.push_notification); the client
    never sends anything back over this socket. History, unread counts and
    marking-as-read all go through the REST API instead (see
    apps.notifications.api) - keeping the socket one-directional avoids
    having to keep client and server state in sync over two channels.
    """

    async def connect(self):
        user = self.scope.get("user")
        if user is None or user.is_anonymous:
            await self.close(code=4401)
            return
        self.group_name = group_name_for(user.id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def notification_push(self, event):
        """Handler for the {"type": "notification.push", ...} group event
        sent by apps.notifications.realtime.push_notification (Channels maps
        the dotted type to this method name)."""
        await self.send_json(event["payload"])
