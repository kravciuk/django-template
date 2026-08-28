"""Настройки для PROD-окружения."""

from .base import *  # noqa: F401,F403
from .base import env, env_list

DEBUG = False

LOGGING_CONFIG = None
LOG_LEVEL = "INFO"

ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", [])

# --- Безопасность ---
SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT", "true").lower() == "true"
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 7  # 7 дней
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
X_FRAME_OPTIONS = "DENY"
# Nginx проксирует HTTPS и добавляет этот заголовок — иначе Django не
# узнает, что запрос изначально пришёл по HTTPS.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# --- Статика (раздаётся Nginx из STATIC_ROOT, см. docker/nginx/nginx.conf) ---
STATIC_ROOT = env("STATIC_ROOT", "/app/static")

# --- База данных через PgBouncer ---
DATABASES["default"].update(  # noqa: F405
    {
        "HOST": env("DB_HOST", "pgbouncer"),
        "PORT": env("DB_PORT", "6432"),
    }
)

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS", [])
CORS_ALLOW_ALL_ORIGINS = False

# Reads the built manifest (src/frontend/dist, baked into the image by
# docker/django/Dockerfile.prod before collectstatic runs) - no dev server
# involved. `dev_mode` is already False from base.py; kept explicit here so
# the two environments' intent is visible side by side.
DJANGO_VITE["default"]["dev_mode"] = False  # noqa: F405
