from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .api import CalendarFeedView, CalendarTagsView, QuickNoteViewSet

app_name = "events"

router = DefaultRouter()
router.register("notes", QuickNoteViewSet, basename="note")

urlpatterns = [
    path("", views.CalendarView.as_view(), name="home"),
    path("api/feed/", CalendarFeedView.as_view(), name="feed"),
    path("api/tags/", CalendarTagsView.as_view(), name="tags"),
    path("api/", include(router.urls)),
]
