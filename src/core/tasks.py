"""
Периодические задачи Celery Beat, зарегистрированные в core/celery.py
(beat_schedule): обновление базы GeoIP и бэкап БД.

Оба таска выполняют соответствующие shell-скрипты из scripts/, которые
монтируются/копируются в контейнер по пути /scripts (см. Dockerfile.dev,
Dockerfile.prod и docker-compose*.yml).
"""

import logging
import os
import subprocess

from celery import shared_task

logger = logging.getLogger("celery")

SCRIPTS_DIR = "/scripts"


def _run_script(script_name, *args):
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    logger.info("Запуск скрипта %s", script_path, extra={"path": script_path})

    result = subprocess.run(
        ["/bin/bash", script_path, *args],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        logger.error(
            "Скрипт %s завершился с ошибкой (код %s): %s",
            script_path, result.returncode, result.stderr,
        )
        raise RuntimeError(f"{script_name} failed with code {result.returncode}: {result.stderr}")

    logger.info("Скрипт %s выполнен успешно", script_path)
    return result.stdout


@shared_task(name="core.tasks.update_geoip_database")
def update_geoip_database():
    """Ежедневное обновление базы GeoLite2-City (03:00, см. core/celery.py)."""
    return _run_script("init_geoip.sh")


@shared_task(name="core.tasks.backup_database")
def backup_database():
    """Ежедневный бэкап БД PostgreSQL (00:00, см. core/celery.py)."""
    return _run_script("backup_db.sh")
