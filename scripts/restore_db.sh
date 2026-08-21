#!/bin/bash
# Восстановление PostgreSQL из бэкапа, созданного backup_db.sh.
# Использование: restore_db.sh /backup/geo_db_20260725_030000.sql.gz
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Использование: $0 <путь_к_backup.sql.gz>" >&2
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "[restore_db] Ошибка: файл '${BACKUP_FILE}' не найден." >&2
    exit 1
fi

DB_NAME="${DB_NAME:?переменная окружения DB_NAME не задана}"
DB_USER="${DB_USER:?переменная окружения DB_USER не задана}"
DB_PASSWORD="${DB_PASSWORD:-}"
PG_HOST="${POSTGRES_HOST:-postgres}"
PG_PORT="${POSTGRES_PORT:-5432}"

echo "[restore_db] Восстановление базы '${DB_NAME}' из ${BACKUP_FILE}..."

gunzip -c "${BACKUP_FILE}" | PGPASSWORD="${DB_PASSWORD}" psql \
    --host="${PG_HOST}" \
    --port="${PG_PORT}" \
    --username="${DB_USER}" \
    --dbname="${DB_NAME}" \
    --set ON_ERROR_STOP=1

echo "[restore_db] Восстановление завершено."
