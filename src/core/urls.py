from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from health_check.views import HealthCheckView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/users/", include("apps.users.urls")),
    path("", include("apps.content.urls")),
    path("documents/", include("apps.documents.urls")),
    path("attachments/", include("apps.attachments.urls")),
    path("s/", include("apps.sharing.urls")),
    path("ckeditor5/", include("django_ckeditor_5.urls")),
    # /health/ исключён из логов через LOG_EXCLUDE_PATHS (см. core/logging.py)
    path("health/", HealthCheckView.as_view(), name="health_check"),
]

if settings.DEBUG:
    # nginx serves /media/ directly in prod (docker/nginx/nginx.conf); dev
    # has no such proxy, so runserver must do it itself or uploads 404.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
