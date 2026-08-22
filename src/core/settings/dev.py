from .base import *  # noqa: F401,F403
from .base import env, env_bool, env_list

DEBUG = True
LOGGING_CONFIG = None
LOG_LEVEL = "DEBUG"

INTERNAL_IPS = env_list("INTERNAL_IPS", ["127.0.0.1", "localhost"])

if env_bool("ENABLE_DEBUG_TOOLBAR", True):
    INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
    MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware"] + MIDDLEWARE  # noqa: F405

DATABASES["default"].update(  # noqa: F405
    {
        "HOST": env("DB_HOST", "pgbouncer"),
        "PORT": env("DB_PORT", "6432"),
    }
)

CORS_ALLOW_ALL_ORIGINS = True
