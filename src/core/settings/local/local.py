"""Личные настройки разработчика поверх DEV-окружения.

Не подключён по умолчанию нигде (ни в manage.py/wsgi.py/asgi.py, ни в
docker-compose.yml) — чтобы использовать, укажи явно:

    DJANGO_SETTINGS_MODULE=core.settings.local.local
"""

from ..dev import *  # noqa: F401,F403

# base.py не задаёт TEMPLATES[0]['OPTIONS']['loaders'], поэтому Django
# всегда оборачивает дефолтные loader'ы в cached.Loader (см. подробный
# комментарий в dev.py) — dev.py уже отключает эту обёртку явным списком
# loader'ов. Повторяем то же самое здесь явно, чтобы local.py не зависел
# от того, что этот блок останется в dev.py неизменным.
TEMPLATES[0]["APP_DIRS"] = False  # noqa: F405
TEMPLATES[0]["OPTIONS"]["loaders"] = [  # noqa: F405
    "django.template.loaders.filesystem.Loader",
    "django.template.loaders.app_directories.Loader",
]
