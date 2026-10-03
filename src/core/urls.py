from allauth.account.decorators import secure_admin_login
from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path
from django.views.i18n import JavaScriptCatalog
from health_check.views import HealthCheckView

from apps.events.google.views import GoogleCallbackView
from apps.events.google.webhook import GoogleCalendarWebhookView

# Route admin's own login page through allauth (2FA/rate-limiting apply
# there too) instead of Django's stock admin login form - otherwise
# /admin/login/ would be a second, unprotected way to authenticate.
admin.site.login = secure_admin_login(admin.site.login)

# Admin/API/health/CKEditor endpoints stay at a fixed, unprefixed path
# regardless of the active language - admin has its own language handling,
# the rest are machine-consumed (JS fetch, monitoring, the editor's upload
# adapter).
urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("api/users/", include("apps.users.urls")),
    path("api/notifications/", include("apps.notifications.urls")),
    path("ckeditor5/", include("django_ckeditor_5.urls")),
    # /health/ is excluded from logs via LOG_EXCLUDE_PATHS (see core/logging.py)
    path("health/", HealthCheckView.as_view(), name="health_check"),
    # Google OAuth redirect URI - must match the one registered in Google
    # Cloud exactly, so it never gets a language prefix (see
    # apps/events/google/views.py).
    path("oauth/google/callback/", GoogleCallbackView.as_view(), name="google_oauth_callback"),
    # Google Calendar push notifications (apps/events/google/webhook.py) -
    # registered with Google per channel, so no language prefix either.
    path("webhooks/google/calendar/", GoogleCalendarWebhookView.as_view(), name="google_calendar_webhook"),
]

# Human-facing pages get a language prefix (/de/..., /fr/..., ...) except the
# default language (English), which stays prefix-free.
#
# The i18n/setlang/ endpoint (django.views.i18n.set_language, used by the
# language switcher) must live INSIDE i18n_patterns too, not alongside the
# fixed-path group above: with prefix_default_language=False, LocaleMiddleware
# forces the *default* language for any request whose own path carries no
# language prefix - if the switcher's own URL were unprefixed, submitting it
# from a German/French/etc. page would itself get forced back to English
# before translate_url() ever runs, so it could never resolve/rewrite the
# "next" URL out of its actual (non-default) language and the switch would
# silently no-op back to the same non-English page.
urlpatterns += i18n_patterns(
    path("i18n/", include("django.conf.urls.i18n")),
    # gettext()/interpolate() for notifications.js/note_autosave.js/
    # tag_autocomplete.js (see templates/base.html) - prefixed for the same
    # reason as i18n/setlang/ above, and so it actually serves the active
    # language's djangojs catalog rather than always the default one.
    path("jsi18n/", JavaScriptCatalog.as_view(), name="javascript-catalog"),
    # Login/logout/signup/password-reset/2FA - see src/templates/allauth/ for
    # the themed templates and core/settings/auth.py for the ACCOUNT_*/MFA_*
    # configuration.
    path("accounts/", include("allauth.urls")),
    path("accounts/", include("apps.users.page_urls")),
    path("", include("apps.content.urls")),
    path("documents/", include("apps.documents.urls")),
    path("attachments/", include("apps.attachments.urls")),
    path("comments/", include("apps.comments.urls")),
    path("s/", include("apps.sharing.urls")),
    path("links/", include("apps.links.urls")),
    path("events/", include("apps.events.urls")),
    prefix_default_language=False,
)

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

    if "debug_toolbar" in settings.INSTALLED_APPS:
        import debug_toolbar

        urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]

