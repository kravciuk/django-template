"""
Celery Beat periodic tasks registered in core/celery.py (beat_schedule): GeoIP
database update.

Runs the corresponding shell script from scripts/, mounted/copied into the
container at /scripts (see Dockerfile.dev, Dockerfile.prod, docker-compose*.yml).

(core.tasks.backup_database used to live here too, driving scripts/backup_db.sh
— removed along with the script: pg_dump in the django image was a major
version behind the server (postgis/postgis:18-3.6) and was silently writing
empty backups. Manual backup/restore is now `make docker-db-backup`/
`docker-db-restore`, see docs/known-issues.md and
docs/operations/running-the-project.md.)
"""

import logging
import os
import subprocess

from celery import shared_task

logger = logging.getLogger("celery")

SCRIPTS_DIR = "/scripts"


def _run_script(script_name, *args):
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    logger.info("Running script %s", script_path, extra={"path": script_path})

    result = subprocess.run(
        ["/bin/bash", script_path, *args],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        logger.error(
            "Script %s failed (code %s): %s",
            script_path, result.returncode, result.stderr,
        )
        raise RuntimeError(f"{script_name} failed with code {result.returncode}: {result.stderr}")

    logger.info("Script %s finished successfully", script_path)
    return result.stdout


@shared_task(name="core.tasks.update_geoip_database")
def update_geoip_database():
    """Daily GeoLite2-City database update (03:00, see core/celery.py)."""
    return _run_script("init_geoip.sh")
