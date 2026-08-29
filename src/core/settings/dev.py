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

# base.py's TEMPLATES doesn't set OPTIONS['loaders'], so django.template.
# engine.Engine.__init__ always wraps the default loaders in cached.Loader -
# unconditionally, regardless of DEBUG (Django 6 dropped the old
# debug-gates-caching behavior). cached.Loader compiles each template once
# and keeps it in memory for the engine's lifetime with no invalidation, so
# an edited template only shows up after the process (the whole container)
# restarts. Listing the loaders explicitly here - with app_directories.Loader
# spelled out instead of APP_DIRS=True, since Engine forbids combining an
# explicit `loaders` with `app_dirs` - opts back out of that wrapping, so
# templates are re-read from disk on every request in dev.
TEMPLATES[0]["APP_DIRS"] = False  # noqa: F405
TEMPLATES[0]["OPTIONS"]["loaders"] = [  # noqa: F405
    "django.template.loaders.filesystem.Loader",
    "django.template.loaders.app_directories.Loader",
]

