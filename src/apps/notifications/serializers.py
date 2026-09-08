from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Read-only: notifications are only ever created through
    apps.notifications.services.notify(), never through this API."""

    sender = serializers.PrimaryKeyRelatedField(read_only=True)
    sender_display = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ["id", "kind", "sender", "sender_display", "payload", "is_read", "read_at", "created_at"]
        read_only_fields = fields

    def get_sender_display(self, obj):
        # None for system-/task-generated notifications (sender is null) -
        # the front-end falls back to a plain kind icon in that case.
        if obj.sender_id is None:
            return None
        return obj.sender.get_full_name() or obj.sender.get_username()
