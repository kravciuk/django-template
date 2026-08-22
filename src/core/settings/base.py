import os
from datetime import timedelta
from pathlib import Path

from core.logging import get_logging_config

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
    "health_check",
    # "django_prometheus",
    "treebeard",
    "taggit",
    "django_ckeditor_5",
    "imagekit",
]

LOCAL_APPS = [
    "apps.users",
    "apps.common",
    "apps.comments",
    "apps.sharing",
    "apps.attachments",
    "apps.content",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    # "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
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
            ],
        },
    },
]

WSGI_APPLICATION = "core.wsgi.application"
ASGI_APPLICATION = "core.asgi.application"

# ---------------------------------------------------------------------------
# База данных (PostGIS через PgBouncer)
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

# There is no user-facing login page yet (apps/users/urls.py is a stub) -
# point LoginRequiredMixin at the working admin login as a pragmatic bridge
# until one exists. Same session auth, just via the existing page.
LOGIN_URL = "/admin/login/"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = env("STATIC_ROOT", "/app/static")

MEDIA_URL = "/media/"
MEDIA_ROOT = env("MEDIA_ROOT", "/app/media")

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
}

# ---------------------------------------------------------------------------
# JWT (rest_framework_simplejwt)
# ---------------------------------------------------------------------------

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(seconds=int(env("JWT_EXPIRATION", "3600"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "SIGNING_KEY": env("JWT_SECRET_KEY", SECRET_KEY),
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------

CELERY_BROKER_URL = env("CELERY_BROKER_URL", "redis://redis:6379/0")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", "redis://redis:6379/0")
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE

CELERY_DEFAULT_QUEUE_NAME = env("CELERY_DEFAULT_QUEUE", "low")
CELERY_HIGH_QUEUE_NAME = env("CELERY_HIGH_QUEUE", "high")

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
# CORS
# ---------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", [])
CORS_ALLOW_CREDENTIALS = True

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

TAGGIT_CASE_INSENSITIVE = True

# Always re-encode generated thumbnails as JPEG regardless of the source
# format - without this, imagekit preserves the source format, and a HEIC
# photo (the default on iPhones) would produce a HEIC "thumbnail" that only
# Safari can actually display in an <img> tag.
IMAGEKIT_DEFAULT_THUMBNAIL_FORMAT = "JPEG"

# CKEditor5 is wired in as a form widget only (apps/content/admin.py) - Note.body
# stays a plain TextField, so the schema never depends on this package.
CKEDITOR_5_CONFIGS = {
    "default": {
        "toolbar": ["heading", "|", "bold", "italic", "link", "bulletedList", "numberedList", "blockQuote"],
    },
    "content_note": {
        "toolbar": [
            "heading", "|",
            "bold", "italic", "underline", "strikethrough", "subscript", "superscript", "|",
            "link", "bulletedList", "numberedList", "blockQuote", "insertTable", "codeBlock", "|",
            "undo", "redo", "sourceEditing",
        ],
        "table": {
            "contentToolbar": ["tableColumn", "tableRow", "mergeTableCells"],
        },
    },
}

ATTACHMENTS_MAX_UPLOAD_SIZE = int(env("ATTACHMENTS_MAX_UPLOAD_SIZE", str(25 * 1024 * 1024)))
ATTACHMENTS_ALLOWED_EXTENSIONS = env_list("ATTACHMENTS_ALLOWED_EXTENSIONS", [])
ATTACHMENTS_MAX_FILES_PER_UPLOAD = int(env("ATTACHMENTS_MAX_FILES_PER_UPLOAD", "10"))

# FileField.max_length on Attachment.file already caps generated paths;
# these two settings cap the actual upload payload size Django will accept.
# Sized for a whole multi-file submission (ATTACHMENTS_MAX_FILES_PER_UPLOAD
# files at ATTACHMENTS_MAX_UPLOAD_SIZE each), not just one file - Django
# enforces these against the total request body, so leaving them at the
# per-file size would 413 a legitimate multi-file upload before any
# per-file validator even runs.
DATA_UPLOAD_MAX_MEMORY_SIZE = ATTACHMENTS_MAX_UPLOAD_SIZE * ATTACHMENTS_MAX_FILES_PER_UPLOAD
FILE_UPLOAD_MAX_MEMORY_SIZE = ATTACHMENTS_MAX_UPLOAD_SIZE * ATTACHMENTS_MAX_FILES_PER_UPLOAD

TRASH_RETENTION_DAYS = int(env("TRASH_RETENTION_DAYS", "30"))
COMMENTS_MAX_DEPTH = int(env("COMMENTS_MAX_DEPTH", "5"))

LOG_LEVEL = env("LOG_LEVEL", "INFO").upper()
LOG_DIR = env("LOG_DIR", "/app/logs")
LOG_CONSOLE_COLOR = env_bool("LOG_CONSOLE_COLOR", False)
MASK_PATTERNS = env_list(
    "MASK_PATTERNS",
    ["password", "token", "refresh", "access", "api_key", "secret", "credit_card"],
)
LOG_EXCLUDE_PATHS = env_list("LOG_EXCLUDE_PATHS", ["/health/", "/metrics/"])

LOGGING = get_logging_config()

import logging.config  # noqa: E402

logging.config.dictConfig(LOGGING)
