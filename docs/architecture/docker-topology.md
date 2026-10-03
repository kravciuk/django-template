# Docker topology

## Dev (`docker-compose.yml`)

| Service | Image / build | Notes |
|---|---|---|
| `postgres` | `docker/postgres/Dockerfile` (`postgis/postgis:18-3.6` + `init-db.sh`) | Enables `postgis`, `postgis_topology`, `hstore`, `uuid-ossp` extensions on first init. Has a real `healthcheck` (`pg_isready`). |
| `redis` | `docker/redis/Dockerfile` (`redis:8.6-trixie`, unmodified) | Broker + Channels layer. |
| `django` | `docker/django/Dockerfile.dev` | Runs `uvicorn core.asgi:application --reload` — **not** `manage.py runserver`, because Channels 4.x has no ASGI `runserver` variant (only `runworker`), and WebSockets need a real ASGI server. `--reload` gives the same "autoreload on edit" behavior `runserver` would. |
| `nginx` | `docker/nginx/Dockerfile` (`NGINX_CONF=nginx.dev.conf`) | Fronts the single `django` container for both HTTP and `/ws/`. |

Dev has **no PgBouncer** — Django connects straight to `postgres` (`.env` overrides `DB_HOST=postgres`,
`DB_PORT=5432`). No Celery workers/beat run in dev either — Celery tasks are defined and importable but nothing
consumes the queue unless you start a worker manually.

Volumes worth knowing:
- `./src:/app` — live source mount, so **editing Python files never requires an image rebuild** in dev; only
  dependency or Dockerfile changes do.
- `./tests:/app/tests`, `./pytest.ini:/app/pytest.ini` — `pytest.ini` and `tests/` live at the **project root**,
  not under `src/`, so without these explicit mounts `make docker-test` / a direct `pytest tests/...` invocation inside
  the container would collect zero tests. Mounting them under `/app` (rather than the container root) makes
  Docker create matching **empty placeholder files** back on the host under `src/pytest.ini` — harmless bind-mount
  artifacts, not real files (see [Known Issues](../known-issues.md)).
- `./var/media`, `./var/static`, `./logs`, `./scripts`, `./backups` — all bind-mounted so runtime state/backups
  survive container recreation and are inspectable from the host.

`docker/nginx/nginx.dev.conf` proxies `/static/` **back to Django** (not aliased to a local directory) —
deliberately, because the image's own baked static snapshot (from the dev image's `collectstatic` step) would go
stale the instant a JS/CSS file changes on the live-mounted `./src`, with no cache-invalidation signal to nginx.
Django itself serves `/static/`/`/media/` in `DEBUG=True` (`core/urls.py` appends
`static()`/`staticfiles_urlpatterns()` when `settings.DEBUG`), so this "double-hop" (nginx → Django → static) is
intentional, not an oversight.

## Prod (`docker-compose.prod.yml`)

Adds `pgbouncer`, splits Django into **two containers from one image** (`project:prod`):

| Service | Command | Notes |
|---|---|---|
| `django` | `gunicorn --config gunicorn.conf.py core.wsgi:application` | Sync workers, runs migrations on entrypoint (`RUN_MIGRATIONS` defaults `true`). |
| `django-ws` | `gunicorn --config gunicorn_asgi.conf.py core.asgi:application` | `UvicornWorker`s, `RUN_MIGRATIONS=false` explicitly (so migrations run exactly once, from `django`, not twice on every deploy). |
| `celery-high` / `celery-low` | `celery -A core worker -Q high` / `-Q low` | One process per queue. |
| `celery-google` / `celery-google-bulk` | `celery -A core worker -Q google` / `-Q google_bulk`, `-O fair --prefetch-multiplier=1` | Google Calendar sync only (`apps.events.tasks`): `google` for syncs someone waits on (push notification, "Sync now", a just-saved note), `google_bulk` for the scheduled ones. Prefork concurrency `CELERY_GOOGLE_CONCURRENCY` (8) / `CELERY_GOOGLE_BULK_CONCURRENCY` (16) — the tasks mostly wait on Google; keep all workers' concurrency together under `PGBOUNCER_MAX_CLIENT_CONN`. |
| `celery-beat` | `celery -A core beat` | Single scheduler instance — never run more than one `beat` process against the same schedule. |
| `pgbouncer` | `docker/pgbouncer/Dockerfile` (`edoburu/pgbouncer` + custom `pgbouncer.ini`) | `pool_mode=transaction`, `auth_type=scram-sha-256`, userlist generated from env by the base image's own entrypoint. |
| `nginx` | `docker/nginx/Dockerfile` (default `nginx.conf`) | Routes `/ws/` → `django-ws`, everything else → `django`; aliases `/static/`/`/media/` to files baked/mounted at build/run time. |

**Build order matters and is not guaranteed by plain `docker compose build`**: `docker/nginx/Dockerfile` does a
multi-stage `COPY --from=project:prod /app/static ...`, so the `django` image must exist *before* nginx is built.
`make docker-prod-build` (and `make docker-build`) build `django` first, then everything else, specifically to guarantee
this — don't replace it with a bare `docker compose build`.

`docker/django/entrypoint.sh` (shared by both `django` and `django-ws` in prod, and by `django` in dev) does, in
order: wait for `DB_HOST:DB_PORT` to accept TCP connections, wait for Redis (parsed from `REDIS_URL`, 30 retries ×
1s), run `manage.py migrate --noinput` unless `RUN_MIGRATIONS=false`, then exec the container's actual command.

Gunicorn configs are deliberately different per role: `gunicorn.conf.py` (HTTP) recycles workers every
1000±50 requests to bound per-worker memory growth; `gunicorn_asgi.conf.py` (WS) disables that recycling entirely
(`max_requests=0`) because a scheduled restart would forcibly drop long-lived WebSocket connections.

## Backups / restore / GeoIP

- **`make docker-db-backup`/`docker-db-restore`** (and `docker-prod-*` twins) — the only backup/restore mechanism
  in the project today; see [operations/running-the-project.md](../operations/running-the-project.md#backups--restore--geoip)
  for the full command reference. Runs `pg_dump -Fc`/`pg_restore` *inside* the `postgres` container itself, via the
  container's own local Unix-socket trust auth (`POSTGRES_USER`/`POSTGRES_DB`, already in its environment). Output
  goes to `backups/backup_<timestamp>.dump` on the host (captured from the `docker compose exec` command's stdout,
  not written by a script inside a mount). `docker-db-restore` auto-picks the most recent `.dump` file if `FILE=`
  is omitted and always prompts for confirmation first. There is **no automated/scheduled backup** — this is a
  manual, operator-run command only.
- `scripts/init_geoip.sh` — downloads MaxMind's `GeoLite2-City` database using `MAXMIND_LICENSE_KEY`; **exits
  successfully with a log message and does nothing** if the key is unset or still the `.env.example` placeholder
  value `your_key` — safe to run with no license key configured, it just skips. Invoked via the Celery Beat task
  `core.tasks.update_geoip_database` (daily, 03:00); no Makefile target for it. Run via
  `_run_script()` in `core/tasks.py` (`subprocess.run(..., check=False)`, manually raises `RuntimeError` on
  non-zero exit — so a failed GeoIP update surfaces as a Celery task failure, not a silent no-op).

There used to be a second path, `scripts/backup_db.sh`/`restore_db.sh` (`pg_dump`/plain-SQL+gzip, run from the
`django` container, driven by a Celery Beat task `core.tasks.backup_database`). It was **removed**: `pg_dump` from
the `django` image's own `postgresql-client` (apt package, v17 on Debian trixie) was a major version behind
`postgis/postgis:18-3.6` (v18), so it aborted with a version-mismatch error on every run while the shell pipeline
still wrote an empty `.sql.gz` file regardless — a silent data-safety bug, confirmed by actually running it. The
`postgresql-client` apt package was removed from both Dockerfiles along with the scripts (nothing else in the
`django` image needs `psql`/`pg_dump`).
