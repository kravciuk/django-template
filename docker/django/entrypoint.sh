#!/bin/bash
set -e

# Ожидание доступности базы данных (через PgBouncer или напрямую)
if [ -n "$DB_HOST" ] && [ -n "$DB_PORT" ]; then
    echo "Ожидание базы данных на ${DB_HOST}:${DB_PORT}..."
    until python - <<PYEOF
import socket
import sys

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.settimeout(1)
try:
    s.connect(("${DB_HOST}", ${DB_PORT}))
except OSError:
    sys.exit(1)
finally:
    s.close()
PYEOF
    do
        echo "База данных недоступна, повтор через 1 секунду..."
        sleep 1
    done
    echo "База данных доступна."
fi

# Ожидание доступности Redis
if [ -n "$REDIS_URL" ]; then
    echo "Ожидание Redis..."
    python - <<PYEOF
import sys
import time
import urllib.parse

url = urllib.parse.urlparse("${REDIS_URL}")
host = url.hostname or "redis"
port = url.port or 6379

import socket
for _ in range(30):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect((host, port))
        s.close()
        sys.exit(0)
    except OSError:
        time.sleep(1)
print("Redis недоступен после ожидания", file=sys.stderr)
sys.exit(1)
PYEOF
    echo "Redis доступен."
fi

# Применение миграций (можно отключить переменной окружения RUN_MIGRATIONS=false)
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
    echo "Применение миграций..."
    python manage.py migrate --noinput
fi

exec "$@"
