#!/bin/bash
set -e

# Официальный образ postgres задаёт POSTGRES_USER / POSTGRES_DB при первом
# запуске. Поддерживаем также DB_USER / DB_NAME на случай, если compose
# передаёт именно их (см. пункт 4.1 плана) — берём то, что задано.
PG_USER="${POSTGRES_USER:-${DB_USER}}"
PG_DB="${POSTGRES_DB:-${DB_NAME}}"

psql -v ON_ERROR_STOP=1 --username "${PG_USER}" --dbname "${PG_DB}" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS postgis;
    CREATE EXTENSION IF NOT EXISTS postgis_topology;
    CREATE EXTENSION IF NOT EXISTS hstore;
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
EOSQL

echo "PostGIS/hstore/uuid-ossp расширения включены для базы ${PG_DB}."
