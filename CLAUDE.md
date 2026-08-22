# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Dockerized Django project template (GeoDjango/PostGIS + REST + JWT + Channels + Celery), built to be cloned as a
starting point for geo-tracking-style services. `apps/users` currently exists only as an empty scaffold (no models,
no views — just a placeholder `urls.py`); this is the pattern to follow when adding new apps under `src/apps/`.

All Django code lives under `src/` (that's the `pythonpath` for pytest and the Docker build context subdir). There
is no top-level `manage.py` — it's at `src/manage.py`.

## Commands

Everything runs through Docker Compose via the `Makefile`; there's no local venv workflow. Dev containers mount
`./src` live, so no rebuild is needed after editing Python files — only after changing dependencies or the Dockerfile.

```bash
make dev-build          # build dev images
make dev-up             # start dev stack detached (postgres, redis, django)
make dev-run            # same, attached (see logs in foreground)
make dev-down           # stop dev stack

make migrate            # python manage.py migrate
make createsuperuser
make shell               # django shell
make test                # pytest, inside the django container

make logs-django         # tail logs/django/django.log
make logs-celery         # tail logs/celery/celery.log
make logs-follow         # docker compose logs -f for django + celery services

make backup                        # dumps DB via scripts/backup_db.sh
make restore FILE=geo_db_*.sql.gz  # restores from ./backups/<FILE>

make prod-build         # builds django image first, then the rest (nginx's
                         # Dockerfile does COPY --from=geo_tracking-django:prod,
                         # so django must exist before nginx builds — plain
                         # `docker compose build` does not guarantee this order)
make prod-up / prod-down
```

To run a single test or pass pytest args (the `test` target takes none), exec directly:

```bash
docker compose -f docker-compose.yml --env-file .env exec django pytest tests/unit/test_x.py::test_it -v
```

Test settings: `pytest.ini` sets `DJANGO_SETTINGS_MODULE=core.settings.dev`, `pythonpath=src`, `testpaths=tests`.
`tests/unit/` and `tests/integration/` currently contain no tests, just `.gitkeep`.

There is no linter/formatter config in the repo (no ruff/flake8/black config) — don't assume one.

## Settings layering

`core/settings/base.py` holds everything common; `dev.py` and `prod.py` do `from .base import *` and override.
`DJANGO_SETTINGS_MODULE` defaults to `core.settings.dev` in `manage.py`, `wsgi.py`, `asgi.py`, and `celery.py` — prod
always sets it explicitly via env (`docker-compose.prod.yml`, `Dockerfile.prod`). All settings are read from env
vars via the `env`/`env_bool`/`env_list` helpers at the top of `base.py`, not hardcoded — check `.env.example` for
the full var list before adding a new setting.

Dev vs prod topology differs, not just settings values:
- **Dev** (`docker-compose.yml`): just `postgres`, `redis`, `django` (runserver). No PgBouncer, no Celery
  workers/beat in dev — Django connects straight to Postgres (`DB_HOST`/`DB_PORT` in `.env`).
- **Prod** (`docker-compose.prod.yml`): adds `pgbouncer` (Django's actual DB host/port in prod), `celery-high`,
  `celery-low`, `celery-beat`, and `nginx` (terminates HTTP, proxies `/ws/` for Channels and `/` to gunicorn, serves
  `/static/` and `/media/` directly). Prod containers read env from `.env.prod`, not `.env`.

## Logging

Logging is entirely custom (`core/logging.py:get_logging_config()`), not Django's default — both `dev.py` and
`prod.py` set `LOGGING_CONFIG = None` and `base.py` calls `logging.config.dictConfig(LOGGING)` itself at import
time. Key points to know before touching logging-adjacent code:

- JSON file logs go to `logs/django/{django,django_error}.log` and `logs/celery/{celery,celery_error}.log`
  (rotating, sizes/counts from `LOG_FILE_MAX_SIZE`/`LOG_FILE_BACKUP_COUNT`); console output is human-readable
  (colorized in dev via `LOG_CONSOLE_COLOR`).
- `MaskSensitiveFilter` redacts values for keys in `MASK_PATTERNS` (password, token, secret, etc.) from log
  messages before they're written — don't bypass this by logging raw dicts as pre-formatted strings.
- `JSONFormatter` expects fields like `client_ip`, `real_ip`, `cf_ip_country`, `cf_ray`, `user_id`, `status_code`,
  `duration_ms` to arrive via `extra={...}` (e.g. from request-logging middleware) — none of that middleware exists
  yet, so these currently log as `null`. If you add request logging, populate via `extra`, not by editing the
  formatter.
- `ExcludeHealthFilter` drops log records whose `record.path` starts with an entry in `LOG_EXCLUDE_PATHS` (health
  checks/metrics) — only takes effect for records that set `path` via `extra`.

## Celery

`core/celery.py` defines the app with two queues, `high` and `low` (default). Routing is by task name suffix:
anything named `*.high_priority_task` goes to `high`; everything else goes to `low`. Beat schedule (in the same
file) runs `core.tasks.update_geoip_database` daily at 03:00 and `core.tasks.backup_database` at 00:00 — both
tasks (`core/tasks.py`) just shell out to `scripts/init_geoip.sh` / `scripts/backup_db.sh` via `subprocess.run`
and raise `RuntimeError` on non-zero exit. Those scripts are copied into the image at `/scripts` (see Dockerfiles),
not run from the repo path directly.

## GeoDjango / Channels

- DB engine is `django.contrib.gis.db.backends.postgis` — this is a GeoDjango project; GDAL/PROJ system libs are
  installed in both Dockerfiles for this reason.
- `GEOIP_PATH` in settings is derived from the `GEOIP_PATH` env var: if that env var ends in `.mmdb`, settings
  strips it down to the containing directory (GeoIP2's Django integration wants a dir, not a file path).
- `core/asgi.py` wires up Channels (`ProtocolTypeRouter` with `AllowedHostsOriginValidator` + `URLRouter`).
  `core/routing.py` (`websocket_urlpatterns`) is currently empty — it's the place to register consumers when a
  real-time app is added.

## REST / auth

DRF is configured with three auth backends stacked (session, DRF token, SimpleJWT) and `IsAuthenticated` as the
default permission — new views inherit "must be logged in" unless they explicitly opt out. JWT lifetime comes from
`JWT_EXPIRATION` (access) with rotating refresh tokens and blacklist-after-rotation enabled.


### Rules

- All code comments are in English only.
- The user answered questions in their native language.
- Do not migrate, do not ask permission, and do not describe the changes you made to the model.
- Operations with the project's Git code repository are performed only upon direct instruction.
- Always use string localization: gettext_lazy for models, gettext for views and translate, blocktranslate in templates.
