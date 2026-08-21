"""Настройки для DEV-окружения."""

from .base import *  # noqa: F401,F403
from .base import env, env_bool, env_list

DEBUG = True

# Django использует собственный dictConfig из core.logging, а не встроенный
# механизм LOGGING_CONFIG.
LOGGING_CONFIG = None
LOG_LEVEL = "DEBUG"

INTERNAL_IPS = env_list("INTERNAL_IPS", ["127.0.0.1", "localhost"])

# Django Debug Toolbar — включается по умолчанию в DEV, можно отключить
# через ENABLE_DEBUG_TOOLBAR=false в .env.dev.
if env_bool("ENABLE_DEBUG_TOOLBAR", True):
    INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
    MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware"] + MIDDLEWARE  # noqa: F405

# База данных через PgBouncer (используем DB_HOST/DB_PORT из .env.dev,
# по умолчанию pgbouncer:6432)
DATABASES["default"].update(  # noqa: F405
    {
        "HOST": env("DB_HOST", "pgbouncer"),
        "PORT": env("DB_PORT", "6432"),
    }
)

# В DEV удобнее разрешить все origins для CORS
CORS_ALLOW_ALL_ORIGINS = True
