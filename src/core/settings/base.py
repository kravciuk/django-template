"""
Базовые настройки Django, общие для DEV и PROD.

Специфичные для окружения значения переопределяются в dev.py / prod.py.
Все переменные читаются из окружения (пробрасываются через env_file в
docker-compose), значения по умолчанию рассчитаны на DEV.
"""

import os
from datetime import timedelta
from pathlib import Path

from core.logging import get_logging_config

# ---------------------------------------------------------------------------
# Вспомогательные функции чтения окружения
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Пути
# ---------------------------------------------------------------------------

# src/core/settings/base.py -> parents[2] == src/
BASE_DIR = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Безопасность
# ---------------------------------------------------------------------------

SECRET_KEY = env("SECRET_KEY", "insecure-secret-key-change-me")
DEBUG = False  # переопределяется в dev.py / prod.py
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

# ---------------------------------------------------------------------------
# Приложения
# ---------------------------------------------------------------------------

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
    # Актуальная версия django-health-check (4.x) — единое приложение,
    # без под-приложений health_check.db/.cache/.storage (это API старых
    # версий 3.x). Проверки регистрируются классами прямо во view,
    # см. core/urls.py.
    "health_check",
    "django_prometheus",
]

LOCAL_APPS = [
    "apps.users",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
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
        # PgBouncer в режиме transaction pooling несовместим с постоянными
        # соединениями и server-side cursors Django — отключаем их.
        "CONN_MAX_AGE": 0,
        "DISABLE_SERVER_SIDE_CURSORS": True,
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# Аутентификация / пароли
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ---------------------------------------------------------------------------
# Интернационализация
# ---------------------------------------------------------------------------

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Статика и медиа (пути внутри контейнера — см. docker-compose volumes)
# ---------------------------------------------------------------------------

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
# Django ожидает в GEOIP_PATH ДИРЕКТОРИЮ с файлами GeoLite2-*.mmdb, а не
# путь к самому файлу. В .env указан полный путь к файлу — нормализуем.
if _geoip_env_path.endswith(".mmdb"):
    GEOIP_PATH = str(Path(_geoip_env_path).parent)
else:
    GEOIP_PATH = _geoip_env_path

# ---------------------------------------------------------------------------
# Логирование (см. core/logging.py). LOGGING_CONFIG = None задаётся в
# dev.py / prod.py, чтобы явно показать, что Django не использует свой
# конфиг логирования по умолчанию.
# ---------------------------------------------------------------------------

LOG_LEVEL = env("LOG_LEVEL", "INFO").upper()
LOG_DIR = env("LOG_DIR", "/app/logs")
LOG_CONSOLE_COLOR = env_bool("LOG_CONSOLE_COLOR", False)
MASK_PATTERNS = env_list(
    "MASK_PATTERNS",
    ["password", "token", "refresh", "access", "api_key", "secret", "credit_card"],
)
LOG_EXCLUDE_PATHS = env_list("LOG_EXCLUDE_PATHS", ["/health/", "/metrics/"])

LOGGING = get_logging_config()

# LOGGING_CONFIG = None задаётся в dev.py/prod.py именно для того, чтобы
# Django НЕ пытался сам применить settings.LOGGING (во избежание двойной
# конфигурации) — поэтому применяем словарь вручную здесь же.
import logging.config  # noqa: E402

logging.config.dictConfig(LOGGING)
