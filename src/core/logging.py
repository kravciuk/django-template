"""
Модуль логирования проекта.

Определяет get_logging_config() — функцию, возвращающую словарь для
logging.config.dictConfig. Используется вместо стандартного механизма
Django (settings.LOGGING_CONFIG = None в dev.py/prod.py). Настройки
(LOG_LEVEL, LOG_DIR и т.д.) читаются из окружения в core/settings/logging.py
и передаются сюда параметрами — этот модуль ничего не знает про Django settings.

Поля client_ip/real_ip/cf_ip_country/cf_ray/method/path/status_code/
duration_ms/user_agent/referer предполагают, что их прокидывают через
`extra={...}` при логировании (например, из middleware логирования
запросов). Если они не переданы — в JSON-логе будут null, это ожидаемо.
"""

import json
import logging
import logging.handlers
import os
import re

MASK_VALUE = "***MASKED***"

DEFAULT_MASK_PATTERNS = [
    "password", "token", "refresh", "access",
    "api_key", "secret", "credit_card",
]

DEFAULT_EXCLUDE_PATHS = ["/health/", "/metrics/"]


class JSONFormatter(logging.Formatter):
    """Форматирует запись лога в одну строку JSON (формат см. в плане)."""

    def format(self, record):
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "user_id": getattr(record, "user_id", None),
            "client_ip": getattr(record, "client_ip", None),
            "real_ip": getattr(record, "real_ip", None),
            "cf_ip_country": getattr(record, "cf_ip_country", None),
            "cf_ray": getattr(record, "cf_ray", None),
            "method": getattr(record, "method", None),
            "path": getattr(record, "path", None),
            "status_code": getattr(record, "status_code", None),
            "duration_ms": getattr(record, "duration_ms", None),
            "user_agent": getattr(record, "user_agent", None),
            "referer": getattr(record, "referer", None),
            "error": None,
        }

        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)
        elif getattr(record, "error", None):
            payload["error"] = record.error

        return json.dumps(payload, ensure_ascii=False, default=str)


class MaskSensitiveFilter(logging.Filter):
    """Маскирует значения чувствительных полей в тексте сообщения лога.

    Обрабатывает как JSON-подобные пары `"key": "value"`, так и
    query/kwargs-подобные `key=value`.
    """

    def __init__(self, patterns=None):
        super().__init__()
        self.patterns = patterns or DEFAULT_MASK_PATTERNS
        self._compiled = [
            (
                re.compile(rf'("{re.escape(key)}"\s*:\s*")([^"]*)(")', re.IGNORECASE),
                re.compile(rf'({re.escape(key)}=)([^\s&,]+)', re.IGNORECASE),
            )
            for key in self.patterns
        ]

    def filter(self, record):
        try:
            message = record.getMessage()
        except Exception:  # сообщение с некорректными args — не трогаем
            return True

        masked = message
        for json_pattern, kv_pattern in self._compiled:
            masked = json_pattern.sub(rf'\1{MASK_VALUE}\3', masked)
            masked = kv_pattern.sub(rf'\1{MASK_VALUE}', masked)

        if masked != message:
            record.msg = masked
            record.args = ()

        return True


class ExcludeHealthFilter(logging.Filter):
    """Отбрасывает записи, у которых record.path относится к health/metrics
    эндпоинтам (path должен быть проставлен через extra=)."""

    def __init__(self, exclude_paths=None):
        super().__init__()
        self.exclude_paths = exclude_paths or DEFAULT_EXCLUDE_PATHS

    def filter(self, record):
        path = getattr(record, "path", None)
        if path and any(path.startswith(prefix) for prefix in self.exclude_paths):
            return False
        return True


class CloudflareIPFilter(logging.Filter):
    """Гарантирует наличие полей client_ip/real_ip/cf_ip_country/cf_ray в
    записи (значения по умолчанию None, если не были переданы через extra=
    в вызывающем коде — обычно middleware запроса)."""

    def filter(self, record):
        for attr in ("client_ip", "real_ip", "cf_ip_country", "cf_ray"):
            if not hasattr(record, attr):
                setattr(record, attr, None)
        return True


def _plain_console_format():
    return {
        "format": "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        "datefmt": "%Y-%m-%d %H:%M:%S",
    }


def _color_console_format():
    return {
        "()": "colorlog.ColoredFormatter",
        "format": "%(log_color)s[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        "datefmt": "%Y-%m-%d %H:%M:%S",
        "log_colors": {
            "DEBUG": "cyan",
            "INFO": "green",
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "bold_red",
        },
    }


def get_logging_config(
    log_level="INFO",
    celery_log_level=None,
    log_dir="/app/logs",
    console_color=False,
    max_bytes=20 * 1024 * 1024,
    backup_count=5,
    mask_patterns=None,
    exclude_paths=None,
    log_sql=False,
):
    """Собирает dictConfig для logging из переданных настроек (см. core.settings.logging)."""

    log_level = log_level.upper()
    celery_log_level = (celery_log_level or log_level).upper()
    mask_patterns = mask_patterns if mask_patterns is not None else DEFAULT_MASK_PATTERNS
    exclude_paths = exclude_paths if exclude_paths is not None else DEFAULT_EXCLUDE_PATHS

    django_log_dir = os.path.join(log_dir, "django")
    celery_log_dir = os.path.join(log_dir, "celery")
    os.makedirs(django_log_dir, exist_ok=True)
    os.makedirs(celery_log_dir, exist_ok=True)

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {"()": "core.logging.JSONFormatter"},
            "console": _color_console_format() if console_color else _plain_console_format(),
        },
        "filters": {
            "mask_sensitive": {
                "()": "core.logging.MaskSensitiveFilter",
                "patterns": mask_patterns,
            },
            "exclude_health": {
                "()": "core.logging.ExcludeHealthFilter",
                "exclude_paths": exclude_paths,
            },
            "cloudflare_ip": {"()": "core.logging.CloudflareIPFilter"},
        },
        "handlers": {
            # Вывод в stdout/stderr — используется и в DEV (цветной), и в
            # PROD (обычный текст), т.к. в контейнерах stdout — стандартный
            # источник логов для docker logs.
            "console_json": {
                "class": "logging.StreamHandler",
                "formatter": "console",
                "filters": ["mask_sensitive", "exclude_health", "cloudflare_ip"],
            },
            "file_django": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": os.path.join(django_log_dir, "django.log"),
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "formatter": "json",
                "filters": ["mask_sensitive", "exclude_health", "cloudflare_ip"],
            },
            "file_django_error": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": os.path.join(django_log_dir, "django_error.log"),
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "level": "ERROR",
                "formatter": "json",
                "filters": ["mask_sensitive", "cloudflare_ip"],
            },
            "file_celery": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": os.path.join(celery_log_dir, "celery.log"),
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "formatter": "json",
                "filters": ["mask_sensitive"],
            },
            "file_celery_error": {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": os.path.join(celery_log_dir, "celery_error.log"),
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "level": "ERROR",
                "formatter": "json",
                "filters": ["mask_sensitive"],
            },
        },
        "loggers": {
            "django": {
                "handlers": ["console_json", "file_django"],
                "level": log_level,
                "propagate": False,
            },
            "django.request": {
                "handlers": ["console_json", "file_django", "file_django_error"],
                "level": log_level,
                "propagate": False,
            },
            # Every SQL query is logged at DEBUG - far too noisy to follow
            # LOG_LEVEL=DEBUG automatically, so it needs an explicit
            # LOG_SQL=true (and only takes effect together with DEBUG).
            "django.db.backends": {
                "handlers": ["console_json"],
                "level": "DEBUG" if log_sql and log_level == "DEBUG" else "WARNING",
                "propagate": False,
            },
            "celery": {
                "handlers": ["file_celery", "file_celery_error", "console_json"],
                "level": celery_log_level,
                "propagate": False,
            },
            "geoip": {
                "handlers": ["console_json", "file_django"],
                "level": log_level,
                "propagate": False,
            },
            "websocket": {
                "handlers": ["console_json", "file_django"],
                "level": log_level,
                "propagate": False,
            },
            # Catches logging.getLogger("apps.<name>") calls from any
            # apps.* package (e.g. apps.content.services' purge warnings) -
            # without this they'd propagate to the unconfigured root logger
            # and be silently dropped.
            "apps": {
                "handlers": ["console_json", "file_django", "file_django_error"],
                "level": log_level,
                "propagate": False,
            },
        },
    }
