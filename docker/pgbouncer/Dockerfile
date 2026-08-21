# syntax=docker/dockerfile:1
FROM edoburu/pgbouncer:latest

# Базовый образ edoburu/pgbouncer умеет генерировать конфигурацию из
# переменных окружения (DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, POOL_MODE,
# MAX_CLIENT_CONN и т.д.) через собственный entrypoint — именно так решена
# "аутентификация через переменные окружения" из плана.
# Наш pgbouncer.ini накладывается поверх как явный слой настроек пула.
COPY docker/pgbouncer/pgbouncer.ini /etc/pgbouncer/pgbouncer.ini
