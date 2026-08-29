# syntax=docker/dockerfile:1
# Dockerfile используется только в PROD (docker-compose.prod.yml).
#
# DJANGO_IMAGE должен указывать на уже собранный prod-образ Django
# (тот же тег, что использует сервис django в docker-compose.prod.yml),
# чтобы забрать из него результат `collectstatic` через multi-stage COPY.
ARG DJANGO_IMAGE=project:latest

FROM ${DJANGO_IMAGE} AS django_static

FROM docker.angie.software/angie:latest

# Фиксируем число воркеров вместо auto-режима по умолчанию.
RUN sed -i 's/^worker_processes\s\+auto;/worker_processes  2;/' /etc/angie/angie.conf

# В DEV используется project:dev, а /ws/ идёт в тот же
# единственный django-контейнер (там нет отдельного django-ws) — см.
# nginx.dev.conf и docker-compose.yml.
ARG NGINX_CONF=nginx.conf

COPY docker/nginx/${NGINX_CONF} /etc/angie/http.d/default.conf

# Статика попадает в образ только на этом шаге (PROD).
COPY --from=django_static /app/static /app/static/
