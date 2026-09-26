import os

from core.logging import get_logging_config

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
CELERY_LOG_LEVEL = os.environ.get("CELERY_LOG_LEVEL", LOG_LEVEL).upper()
LOG_DIR = os.environ.get("LOG_DIR", "/app/logs")
LOG_CONSOLE_COLOR = os.environ.get("LOG_CONSOLE_COLOR", "false").strip().lower() in (
    "1", "true", "yes", "on",
)
LOG_FILE_MAX_SIZE = int(os.environ.get("LOG_FILE_MAX_SIZE", "20")) * 1024 * 1024
LOG_FILE_BACKUP_COUNT = int(os.environ.get("LOG_FILE_BACKUP_COUNT", "5"))
MASK_PATTERNS = [
    p.strip()
    for p in os.environ.get(
        "MASK_PATTERNS", "password,token,refresh,access,api_key,secret,credit_card"
    ).split(",")
    if p.strip()
]
LOG_EXCLUDE_PATHS = [
    p.strip()
    for p in os.environ.get("LOG_EXCLUDE_PATHS", "/health/,/metrics/").split(",")
    if p.strip()
]

LOGGING = get_logging_config(
    log_level=LOG_LEVEL,
    celery_log_level=CELERY_LOG_LEVEL,
    log_dir=LOG_DIR,
    console_color=LOG_CONSOLE_COLOR,
    max_bytes=LOG_FILE_MAX_SIZE,
    backup_count=LOG_FILE_BACKUP_COUNT,
    mask_patterns=MASK_PATTERNS,
    exclude_paths=LOG_EXCLUDE_PATHS,
)
