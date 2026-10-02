import os
from pathlib import Path

from .additional import *  # noqa: F401,F403
from .auth import *  # noqa: F401,F403
from .celery import *  # noqa: F401,F403
from .constance import *  # noqa: F401,F403
from .logging import *  # noqa: F401,F403
from .regional import *  # noqa: F401,F403
from .rest import *  # noqa: F401,F403

def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_list(key, default=None, sep=","):
    value = os.environ.get(key)
    if not value:
        return list(default) if default else []
    return [item.strip() for item in value.split(sep) if item.strip()]


BASE_DIR = Path(__file__).resolve().parents[2]

SECRET_KEY = env("SECRET_KEY", "insecure-secret-key-change-me")
DEBUG = False
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

CORS_ALLOWED_ORIGINS = []
CSRF_TRUSTED_ORIGINS = []
for host in ALLOWED_HOSTS:
    CORS_ALLOWED_ORIGINS.append(f"http://{host}")
    CORS_ALLOWED_ORIGINS.append(f"https://{host}")
    CSRF_TRUSTED_ORIGINS.append(f"http://{host}")
    CSRF_TRUSTED_ORIGINS.append(f"https://{host}")

ADMIN_URL = env("DJANGO_ADMIN_URL", "admin").strip("/") + "/"

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "channels",
    "corsheaders",
    "django_htmx",
    "health_check",
    # "django_prometheus",
    "treebeard",
    "taggit",
    "django_ckeditor_5",
    "imagekit",
    "django_tables2",
    "django_filters",
    "constance",
    "constance.backends.database",
    # User-facing auth (login/signup/password reset/2FA) - see
    # core/settings/auth.py for all the ACCOUNT_*/MFA_* configuration.
    "allauth",
    "allauth.account",
    "allauth.mfa",
]

LOCAL_APPS = [
    "apps.users",
    "apps.common",
    "apps.comments",
    "apps.sharing",
    "apps.attachments",
    "apps.content",
    "apps.documents",
    "apps.links",
    "apps.notifications",
    "apps.events",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    # "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    # Must come after SessionMiddleware (reads the language from the session)
    # and before CommonMiddleware (which needs the active language already
    # resolved) - see Django's own middleware ordering docs.
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Must come after AuthenticationMiddleware - activates request.user's
    # profile time zone (apps.users.models.User.timezone).
    "apps.users.middleware.UserTimezoneMiddleware",
    # Must come after AuthenticationMiddleware - allauth's middleware reads
    # request.user and intercepts flows like "email change must reauthenticate".
    "allauth.account.middleware.AccountMiddleware",
    # Must come after AuthenticationMiddleware - it reads request.user.
    "django_htmx.middleware.HtmxMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "core.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.users.context_processors.account_allow_signup",
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"

# ---------------------------------------------------------------------------
# Database (PostGIS via PgBouncer)
# ---------------------------------------------------------------------------

DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME": env("DB_NAME", "geo_db"),
        "USER": env("DB_USER", "geo_user"),
        "PASSWORD": env("DB_PASSWORD", ""),
        "HOST": env("DB_HOST", "pgbouncer"),
        "PORT": env("DB_PORT", "6432"),
        "CONN_MAX_AGE": 0,
        "DISABLE_SERVER_SIDE_CURSORS": True,
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "users.User"

# LOGIN_URL points at allauth's login view (settings/auth.py) - see
# apps.users.adapter and core/urls.py for how django.contrib.admin's own
# login is folded into the same flow (2FA/rate-limit apply there too).
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

# django.contrib.messages' default tags are success/info/warning/error -
# "error" doesn't match a Bootstrap alert-* class (it's alert-danger), and
# allauth relies on the messages framework for post-redirect notices
# (password changed, logged out, email confirmed...) rendered in base.html.
from django.contrib.messages import constants as message_constants  # noqa: E402

MESSAGE_TAGS = {
    message_constants.ERROR: "danger",
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

STATIC_URL = "/static/"
STATIC_ROOT = env("STATIC_ROOT", "/app/static")

MEDIA_URL = "/media/"
MEDIA_ROOT = env("MEDIA_ROOT", "/app/media")

# ---------------------------------------------------------------------------
# Channels (Redis layer)
# ---------------------------------------------------------------------------

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [env("REDIS_URL", "redis://redis:6379/0")],
        },
    },
}

# ---------------------------------------------------------------------------
# GeoIP2
# ---------------------------------------------------------------------------

_geoip_env_path = env("GEOIP_PATH", "/app/geoip")
if _geoip_env_path.endswith(".mmdb"):
    GEOIP_PATH = str(Path(_geoip_env_path).parent)
else:
    GEOIP_PATH = _geoip_env_path

# ---------------------------------------------------------------------------
# Personal content store (apps.common/comments/sharing/attachments/content)
# ---------------------------------------------------------------------------
#
# ATTACHMENTS_MAX_UPLOAD_SIZE, ATTACHMENTS_ALLOWED_EXTENSIONS,
# ATTACHMENTS_MAX_FILES_PER_UPLOAD, TRASH_RETENTION_DAYS,
# DRAFT_RETENTION_DAYS, COMMENTS_MAX_DEPTH and NOTIFICATIONS_RETENTION_DAYS
# moved to constance (see core/settings/constance.py) - runtime-editable from
# /admin/constance/config/, application code reads them via
# `from constance import config` instead of `django.conf.settings`.

# FileField.max_length on Attachment.file already caps generated paths;
# these two settings cap the actual upload payload size Django will accept.
# Sized for a whole multi-file submission (CONSTANCE_CONFIG's
# ATTACHMENTS_MAX_FILES_PER_UPLOAD files at ATTACHMENTS_MAX_UPLOAD_SIZE each),
# not just one file - Django enforces these against the total request body,
# so leaving them at the per-file size would 413 a legitimate multi-file
# upload before any per-file validator even runs. These are real Django
# framework settings read outside of any request-scoped hook, so they can't
# themselves come from constance (DB-backed, only readable once apps are
# ready) - sized off the same defaults constance starts with; bumping the
# limit at runtime via the admin needs a redeploy to raise the cap here too.
DATA_UPLOAD_MAX_MEMORY_SIZE = (
    CONSTANCE_CONFIG["ATTACHMENTS_MAX_UPLOAD_SIZE"][0]
    * CONSTANCE_CONFIG["ATTACHMENTS_MAX_FILES_PER_UPLOAD"][0]
)
FILE_UPLOAD_MAX_MEMORY_SIZE = DATA_UPLOAD_MAX_MEMORY_SIZE

import logging.config  # noqa: E402

logging.config.dictConfig(LOGGING)
