from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Read-only: notifications are only ever created through
    apps.notifications.services.notify(), never through this API."""

    sender = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Notification
        fields = ["id", "kind", "sender", "payload", "is_read", "read_at", "created_at"]
        read_only_fields = fields
