#!/bin/bash
# Бэкап PostgreSQL: pg_dump -> gzip, с временной меткой в имени файла и
# удалением бэкапов старше BACKUP_RETENTION_DAYS дней.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backup}"
DB_NAME="${DB_NAME:?переменная окружения DB_NAME не задана}"
DB_USER="${DB_USER:?переменная окружения DB_USER не задана}"
DB_PASSWORD="${DB_PASSWORD:-}"
PG_HOST="${POSTGRES_HOST:-postgres}"
PG_PORT="${POSTGRES_PORT:-5432}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
FILENAME="${DB_NAME}_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

echo "[backup_db] Создание бэкапа базы '${DB_NAME}' -> ${BACKUP_DIR}/${FILENAME}"

PGPASSWORD="${DB_PASSWORD}" pg_dump \
    --host="${PG_HOST}" \
    --port="${PG_PORT}" \
    --username="${DB_USER}" \
    --format=plain \
    --no-owner \
    "${DB_NAME}" | gzip > "${BACKUP_DIR}/${FILENAME}"

echo "[backup_db] Бэкап создан: ${BACKUP_DIR}/${FILENAME}"

echo "[backup_db] Удаление бэкапов старше ${RETENTION_DAYS} дней..."
find "${BACKUP_DIR}" -maxdepth 1 -name "${DB_NAME}_*.sql.gz" -type f -mtime "+${RETENTION_DAYS}" -print -delete

echo "[backup_db] Готово."
