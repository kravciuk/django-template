from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .google import views as google_views
from .api import CalendarFeedView, CalendarTagsView, QuickNoteViewSet

app_name = "events"

router = DefaultRouter()
router.register("notes", QuickNoteViewSet, basename="note")

urlpatterns = [
    path("", views.CalendarView.as_view(), name="home"),
    path("api/feed/", CalendarFeedView.as_view(), name="feed"),
    path("api/tags/", CalendarTagsView.as_view(), name="tags"),
    path("api/", include(router.urls)),
    path("google/", google_views.GoogleCalendarSettingsView.as_view(), name="google_settings"),
    path("google/oauth-client/", google_views.GoogleOAuthClientView.as_view(), name="google_oauth_client"),
    path("google/connect/", google_views.GoogleConnectView.as_view(), name="google_connect"),
    path("google/disconnect/", google_views.GoogleDisconnectView.as_view(), name="google_disconnect"),
    path("google/sync/", google_views.GoogleSyncNowView.as_view(), name="google_sync"),
]
