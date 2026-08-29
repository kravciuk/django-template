from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path
from health_check.views import HealthCheckView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/users/", include("apps.users.urls")),
    path("", include("apps.content.urls")),
    path("documents/", include("apps.documents.urls")),
    path("attachments/", include("apps.attachments.urls")),
    path("comments/", include("apps.comments.urls")),
    path("s/", include("apps.sharing.urls")),
    path("ckeditor5/", include("django_ckeditor_5.urls")),
    # /health/ исключён из логов через LOG_EXCLUDE_PATHS (см. core/logging.py)
    path("health/", HealthCheckView.as_view(), name="health_check"),
]

if settings.DEBUG:
    # nginx serves /media/ directly in prod (docker/nginx/nginx.conf); dev
    # has no such proxy, so runserver must do it itself or uploads 404.
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

    # dev runs `uvicorn core.asgi:application` (see docker-compose.yml), not
    # `manage.py runserver` (channels 4.x has no ASGI runserver override, so
    # WebSocket needs a real ASGI server even in dev). runserver used to wrap
    # the handler and serve STATIC_URL implicitly - without it we must add
    # the staticfiles urlpatterns explicitly, or admin/DRF/ckeditor/debug
    # toolbar static assets 404.
    urlpatterns += staticfiles_urlpatterns()

    # dev.py wires DebugToolbarMiddleware in unconditionally, but the
    # toolbar's own template reverses `djdt:...` - without its urls
    # included, that raises NoReverseMatch and 500s every single page.
    import debug_toolbar

    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
