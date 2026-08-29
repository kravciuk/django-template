from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views
from .api import LinkGroupViewSet, LinkViewSet

app_name = "links"

router = DefaultRouter()
router.register("groups", LinkGroupViewSet, basename="group")
router.register("links", LinkViewSet, basename="link")

urlpatterns = [
    path("", views.LinksHomeView.as_view(), name="home"),
    path("api/", include(router.urls)),
]
