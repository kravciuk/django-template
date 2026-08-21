# syntax=docker/dockerfile:1
FROM postgis/postgis:18-3.6

# Скрипт кладём в стандартную директорию docker-entrypoint-initdb.d —
# официальный образ postgres выполняет всё содержимое этой папки
# автоматически при первой инициализации кластера БД.
COPY docker/postgres/init-db.sh /docker-entrypoint-initdb.d/init-db.sh
RUN chmod +x /docker-entrypoint-initdb.d/init-db.sh
