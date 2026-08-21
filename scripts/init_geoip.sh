#!/bin/bash
# Скачивает (и обновляет) базу GeoLite2-City от MaxMind.
# Требует переменную окружения MAXMIND_LICENSE_KEY (реальный ключ,
# получается бесплатно на maxmind.com после регистрации).
set -euo pipefail

GEOIP_DIR="${GEOIP_DIR:-/app/geoip}"
EDITION_ID="GeoLite2-City"
GEOIP_FILE="${GEOIP_DIR}/${EDITION_ID}.mmdb"

if [ -z "${MAXMIND_LICENSE_KEY:-}" ] || [ "${MAXMIND_LICENSE_KEY}" = "your_key" ]; then
    echo "[init_geoip] MAXMIND_LICENSE_KEY не задан (или используется значение-заглушка из .env) — пропускаю загрузку." >&2
    exit 0
fi

DOWNLOAD_URL="https://download.maxmind.com/app/geoip_download?edition_id=${EDITION_ID}&license_key=${MAXMIND_LICENSE_KEY}&suffix=tar.gz"

mkdir -p "${GEOIP_DIR}"

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

echo "[init_geoip] Скачивание базы ${EDITION_ID}..."
curl -fsSL -o "${TMP_DIR}/geoip.tar.gz" "${DOWNLOAD_URL}"

echo "[init_geoip] Проверка целостности архива..."
if ! tar -tzf "${TMP_DIR}/geoip.tar.gz" >/dev/null 2>&1; then
    echo "[init_geoip] Ошибка: скачанный архив повреждён." >&2
    exit 1
fi

tar -xzf "${TMP_DIR}/geoip.tar.gz" -C "${TMP_DIR}"

MMDB_PATH="$(find "${TMP_DIR}" -name "${EDITION_ID}.mmdb" | head -n 1)"

if [ -z "${MMDB_PATH}" ]; then
    echo "[init_geoip] Ошибка: файл ${EDITION_ID}.mmdb не найден в скачанном архиве." >&2
    exit 1
fi

cp "${MMDB_PATH}" "${GEOIP_FILE}"

echo "[init_geoip] База GeoIP обновлена: ${GEOIP_FILE}"
