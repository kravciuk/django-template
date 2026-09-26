# Running the project

Everything runs through Docker Compose via the `Makefile`; there is no local venv workflow. Dev containers mount
`./src` live, so editing Python files never requires a rebuild — only dependency or Dockerfile changes do.

```bash
make docker-build              # builds django first, then everything else (build-order requirement, see docker-topology.md)
make docker-build-nc           # same, ignoring the build cache
make docker-up                 # start dev stack detached (postgres, redis, django, nginx)
make docker-run                # same, attached (logs in foreground)
make docker-down               # stop dev stack
make docker-down-v             # stop dev stack AND drop named volumes (postgres/redis data!)

make docker-restart service=django   # restart one service (omit service= to restart everything)
make docker-ps                       # docker compose ps
make docker-logs service=django      # follow one service's container logs (omit service= for all)

make docker-migrate app=content      # python manage.py migrate (omit app= to migrate everything)
make docker-fakemigrate app=content  # python manage.py migrate --fake
make docker-commit app=content       # python manage.py makemigrations content
make docker-mergemigrations          # python manage.py makemigrations --merge
make docker-createsuperuser
make docker-shell                    # django shell (manage.py shell)
make docker-bash                     # bash inside the django container
make docker-console app="some_command --flag"  # any manage.py command
make docker-test                     # pytest, inside the django container
make docker-test args="tests/unit/test_x.py::test_it -v"  # a single test / extra pytest args

make docker-logs-django         # tail logs/django/django.log (real log file, not container stdout)
make docker-logs-celery         # tail logs/celery/celery.log

make docker-db-backup                     # pg_dump -Fc run inside the postgres container -> backups/*.dump
make docker-db-list                       # list ./backups/*.dump, most recent first
make docker-db-restore                    # restore the most recent .dump backup — asks for confirmation first
make docker-db-restore FILE=backup_*.dump # restore a specific backup instead

make docker-prod-build / docker-prod-up / docker-prod-down / ...  # every target above has a docker-prod-* twin
```

Every dev target has a `docker-prod-*` counterpart running against `docker-compose.prod.yml` instead (e.g.
`docker-prod-migrate`, `docker-prod-db-restore`) — see the `Makefile` itself for the full list; `docker-prod-test`
does not exist since `pytest` is dev-only (`requirements/prod.txt` never installs it).

**`make docker-prod-build`/`make docker-build` build the `django` image before anything else on purpose** —
`docker/nginx/Dockerfile` does a multi-stage `COPY --from=project:{dev,prod}`, so nginx's build fails (or uses a
stale image) if django hasn't been built first. A bare `docker compose build` does not guarantee this ordering —
always go through `make`, not a raw compose invocation, when building images.

Both `docker-build`/`docker-up` (and their `docker-prod-*` twins) depend on a `docker-env` target that copies
`.env.example` → `.env` if `.env` doesn't exist yet, and a `var` target that creates `logs/{django,celery}`,
`var/{media,static}`, and `backups/` if missing — so a fresh checkout can go straight to `make docker-up` without
any manual setup step.

## Running a single test / passing pytest args

```bash
make docker-test args="tests/unit/test_x.py::test_it -v"
```

is equivalent to:

```bash
docker compose -f docker-compose.yml --env-file .env exec django pytest tests/unit/test_x.py::test_it -v
```

See [testing.md](testing.md) for what's actually covered and the one currently-failing test.

## Verified for this review

The dev stack was actually brought up end-to-end while writing this documentation:

```bash
docker compose -f docker-compose.yml --env-file .env up -d
```

Result: `postgres` became healthy, migrations ran cleanly with `entrypoint.sh`'s automatic `migrate --noinput`,
and `django`/`nginx` started with no errors. Smoke-tested routes: `GET /` → 200, `GET /admin/login/` → 200,
`GET /static/admin/css/base.css` → 200, `GET /documents/` (anonymous) → 302 (redirects to login, as expected).
`GET /health/` → 500 — this is investigated and explained in
[known-issues.md](../known-issues.md#ki-3-health-check-returns-500), not a stack failure.

## Environment files

- `.env` / `.env.prod` hold real secrets and are gitignored (`.gitignore`: `.env`, `.env.*`, `!.env.example`).
  `.env.example` is the only one checked into git and documents every variable with safe placeholder values.
- Dev's actual `.env` (not committed) overrides `DB_HOST=postgres`/`DB_PORT=5432` — i.e. dev bypasses PgBouncer
  entirely, even though `base.py`'s own defaults point at `pgbouncer:6432` (there's no PgBouncer service in dev's
  `docker-compose.yml` at all).

## Backups / restore / GeoIP

`make docker-db-backup`/`docker-db-restore` (and their `docker-prod-*` twins) are the only backup/restore
mechanism in the project — `pg_dump -Fc`/`pg_restore` run *inside* the `postgres` container itself, writing
`backups/backup_<timestamp>.dump`. Verified working end-to-end while setting this up: a real dump, successful
restore, DB fully queryable afterward. There is **no automated/scheduled backup** — run `make docker-db-backup`
yourself (or wire it into an external cron) if you want one on a schedule.

An earlier mechanism, `scripts/backup_db.sh`/`restore_db.sh` (plain-SQL + gzip, driven by a Celery Beat task
`core.tasks.backup_database`, daily 00:00), was **removed**: `pg_dump` run from the `django` container was a
major version behind the `postgres` service's own image and silently produced empty backup files every time — a
real data-safety bug, only found by actually running the command while writing the docs for it. The
`postgresql-client` apt package was also removed from both Dockerfiles (nothing else needed it).

See [architecture/docker-topology.md](../architecture/docker-topology.md#backups--restore--geoip) for
`scripts/init_geoip.sh`'s exact behavior and how it's wired into Celery Beat, plus the removed backup mechanism's
history.

## Manual maintenance not currently automated

Run `purge_trash` yourself (or add it to Beat/cron) to actually reclaim space from soft-deleted rows — see
[background-jobs/celery.md](../background-jobs/celery.md#beat-schedule-corecelerypyappconfbeat_schedule):

```bash
make docker-console app="purge_trash --dry-run"
make docker-console app="purge_trash"
```
