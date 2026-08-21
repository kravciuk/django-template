from django.contrib import admin
from django.urls import include, path
from health_check.views import HealthCheckView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/users/", include("apps.users.urls")),
    # /health/ исключён из логов через LOG_EXCLUDE_PATHS (см. core/logging.py)
    path("health/", HealthCheckView.as_view(), name="health_check"),
]
