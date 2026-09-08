from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Notification
from .serializers import NotificationSerializer


class NotificationViewSet(mixins.DestroyModelMixin, viewsets.ReadOnlyModelViewSet):
    """A user's own notification inbox - list/retrieve plus read-tracking
    actions, plus DELETE to let a user dismiss ("stop showing") a single
    notification. Notifications themselves are only ever created through
    apps.notifications.services.notify(), never via this API.

    DestroyModelMixin reuses the existing {basename}-detail URL (just adds
    the DELETE method to it) - get_queryset() below already scopes to the
    logged-in user's own notifications, so deleting someone else's row 404s
    the same way mark_read does."""

    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(recipient=self.request.user)

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_read()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        self.get_queryset().filter(is_read=False).update(is_read=True, read_at=timezone.now())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"])
    def unread_count(self, request):
        return Response({"count": self.get_queryset().filter(is_read=False).count()})
