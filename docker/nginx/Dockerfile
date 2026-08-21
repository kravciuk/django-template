# syntax=docker/dockerfile:1
# Dockerfile используется только в PROD (docker-compose.prod.yml).
#
# DJANGO_IMAGE должен указывать на уже собранный prod-образ Django
# (тот же тег, что использует сервис django в docker-compose.prod.yml),
# чтобы забрать из него результат `collectstatic` через multi-stage COPY.
ARG DJANGO_IMAGE=geo_tracking-django:latest

FROM ${DJANGO_IMAGE} AS django_static

FROM docker.angie.software/angie:latest

COPY docker/nginx/nginx.conf /etc/angie/http.d/default.conf

# Статика попадает в образ только на этом шаге (PROD).
COPY --from=django_static /app/static /app/static/
