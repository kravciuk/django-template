SHELL := /bin/bash

# Explicit -f/--env-file flags (rather than relying on docker compose's implicit
# .env auto-load) so these targets behave the same regardless of cwd quirks.
# Both dev and prod pass --env-file .env: it's used for docker-compose.yml's own
# variable interpolation (e.g. ${DB_NAME} in docker-compose.prod.yml); the actual
# runtime env inside prod containers comes from each service's own
# `env_file: .env.prod`, not from this flag.
COMPOSE_DEV  = docker compose -f docker-compose.yml --env-file .env
COMPOSE_PROD = docker compose -f docker-compose.prod.yml --env-file .env

all: ;@echo 'Run with option (docker-up, docker-prod-up, etc — see Makefile)'

docker-env:
	test -f .env || cp .env.example .env

var:
	mkdir -p logs/django logs/celery var/media var/static backups

# =============================================================================
# Docker — DEV (docker-compose.yml: postgres, redis, django, nginx)
#   django runs `uvicorn core.asgi:application --reload` — no PgBouncer, no
#   Celery worker/beat in dev. See docs/architecture/docker-topology.md.
# =============================================================================

# django is built first: docker/nginx/Dockerfile does a multi-stage
# COPY --from=project:dev, so the django image must exist before nginx builds
# — plain `docker compose build` does not guarantee this order.
docker-build: docker-env var
	$(COMPOSE_DEV) build django
	$(COMPOSE_DEV) build

# rebuild ignoring the build cache (e.g. after changing a Dockerfile/apt package)
docker-build-nc: docker-env var
	$(COMPOSE_DEV) build django --no-cache
	$(COMPOSE_DEV) build --no-cache

docker-run: docker-env var
	$(COMPOSE_DEV) up

docker-up: docker-env var
	$(COMPOSE_DEV) up -d

docker-down:
	$(COMPOSE_DEV) down

# same as docker-down, but also drops named volumes (postgres/redis data!)
docker-down-v:
	$(COMPOSE_DEV) down -v

# make docker-restart service=django  (omit service= to restart everything)
docker-restart:
	$(COMPOSE_DEV) restart ${service}

docker-ps:
	$(COMPOSE_DEV) ps

# make docker-logs service=django  (omit service= to follow every container)
docker-logs:
	$(COMPOSE_DEV) logs -f ${service}

docker-logs-django:
	tail -n 200 -f logs/django/django.log

docker-logs-celery:
	tail -n 200 -f logs/celery/celery.log

docker-shell:
	$(COMPOSE_DEV) exec django python manage.py shell

docker-bash:
	$(COMPOSE_DEV) exec django bash

# make docker-console app="some_command --flag"
docker-console:
	$(COMPOSE_DEV) exec django python manage.py ${app} --traceback

# make docker-migrate app=cars  (omit app= to migrate everything)
docker-migrate:
	$(COMPOSE_DEV) exec django python manage.py migrate ${app}

docker-fakemigrate:
	$(COMPOSE_DEV) exec django python manage.py migrate --fake ${app}

# make docker-commit app=content  (creates migrations for one app)
docker-commit:
	$(COMPOSE_DEV) exec django python manage.py makemigrations ${app}

docker-mergemigrations:
	$(COMPOSE_DEV) exec django python manage.py makemigrations --merge

docker-createsuperuser:
	$(COMPOSE_DEV) exec django python manage.py createsuperuser

# make docker-test args="tests/unit/test_x.py::test_it -v"  (omit args= for the whole suite)
docker-test:
	$(COMPOSE_DEV) exec django pytest ${args}

# pg_dump runs *inside* the postgres container itself, using its own matching
# pg_dump build — the django image's own `postgresql-client` used to be a
# major version behind postgis/postgis:18-3.6 (pg_dump would refuse to talk to
# a newer server at all), which is why this doesn't exec into django instead;
# see docs/known-issues.md for the history. -Fc (custom format) is compressed
# and supports selective/parallel restore. Auth is via the postgres
# container's own local Unix-socket trust rule (POSTGRES_USER/POSTGRES_DB are
# already in its own environment) — no password needed, and `-T` disables pty
# allocation so the dump bytes on stdout aren't corrupted by tty translation.
docker-db-backup: var
	$(COMPOSE_DEV) exec -T postgres sh -c 'pg_dump -Fc -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' \
		> backups/backup_$(shell date +%Y%m%d_%H%M%S).dump
	@echo "Backup written to backups/"

docker-db-list:
	@ls -t backups/*.dump 2>/dev/null || echo "No backups found in ./backups"

# make docker-db-restore FILE=backup_20260926_072416.dump  (omit FILE= to use
# the most recent .dump backup in ./backups) — asks for confirmation first,
# since this overwrites the current database. --clean --if-exists drops
# existing objects before recreating them; --no-owner avoids role-mismatch
# errors when restoring under a different Postgres user than the dump was
# taken from.
docker-db-restore:
	@file="$(FILE)"; \
	if [ -z "$$file" ]; then \
		latest=$$(ls -t backups/*.dump 2>/dev/null | head -n1); \
		if [ -z "$$latest" ]; then echo "No backups found in ./backups"; exit 1; fi; \
		file=$$(basename "$$latest"); \
		echo "No FILE= given — using most recent backup: $$file"; \
	fi; \
	read -p "Restore $$file into the current database? This overwrites all data. [y/N] " confirm; \
	if [ "$$confirm" != "y" ] && [ "$$confirm" != "Y" ]; then echo "Aborted."; exit 1; fi; \
	cat "backups/$$file" | $(COMPOSE_DEV) exec -T postgres sh -c 'pg_restore --clean --if-exists --no-owner -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

# =============================================================================
# Docker — PROD (docker-compose.prod.yml: adds pgbouncer, django-ws,
#   celery-high/celery-low/celery-google/celery-google-bulk/celery-beat, nginx). Mirrors every DEV target above.
#   See docs/architecture/docker-topology.md.
# =============================================================================

docker-prod-build: docker-env var
	$(COMPOSE_PROD) build django
	$(COMPOSE_PROD) build

docker-prod-build-nc: docker-env var
	$(COMPOSE_PROD) build django --no-cache
	$(COMPOSE_PROD) build --no-cache

docker-prod-run: docker-env var
	$(COMPOSE_PROD) up

docker-prod-up: docker-env var
	$(COMPOSE_PROD) up -d

docker-prod-down:
	$(COMPOSE_PROD) down

# same as docker-prod-down, but also drops named volumes (postgres/redis data!)
docker-prod-down-v:
	$(COMPOSE_PROD) down -v

# make docker-prod-restart service=celery-high  (omit service= to restart everything)
docker-prod-restart:
	$(COMPOSE_PROD) restart ${service}

docker-prod-ps:
	$(COMPOSE_PROD) ps

# make docker-prod-logs service=celery-high  (omit service= to follow every container)
docker-prod-logs:
	$(COMPOSE_PROD) logs -f ${service}

docker-prod-shell:
	$(COMPOSE_PROD) exec django python manage.py shell

docker-prod-bash:
	$(COMPOSE_PROD) exec django bash

# make docker-prod-console app="some_command --flag"
docker-prod-console:
	$(COMPOSE_PROD) exec django python manage.py ${app} --traceback

# make docker-prod-migrate app=cars  (omit app= to migrate everything — note the
# django/django-ws entrypoints already migrate on startup unless RUN_MIGRATIONS=false)
docker-prod-migrate:
	$(COMPOSE_PROD) exec django python manage.py migrate ${app}

docker-prod-fakemigrate:
	$(COMPOSE_PROD) exec django python manage.py migrate --fake ${app}

# make docker-prod-commit app=content  (creates migrations for one app)
docker-prod-commit:
	$(COMPOSE_PROD) exec django python manage.py makemigrations ${app}

docker-prod-mergemigrations:
	$(COMPOSE_PROD) exec django python manage.py makemigrations --merge

docker-prod-createsuperuser:
	$(COMPOSE_PROD) exec django python manage.py createsuperuser

# see docker-db-backup above for why this runs inside postgres, not django.
docker-prod-db-backup: var
	$(COMPOSE_PROD) exec -T postgres sh -c 'pg_dump -Fc -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"' \
		> backups/backup_$(shell date +%Y%m%d_%H%M%S).dump
	@echo "Backup written to backups/"

docker-prod-db-list:
	@ls -t backups/*.dump 2>/dev/null || echo "No backups found in ./backups"

# make docker-prod-db-restore FILE=backup_20260926_072416.dump  (omit FILE= to
# use the most recent .dump backup) — asks for confirmation first.
docker-prod-db-restore:
	@file="$(FILE)"; \
	if [ -z "$$file" ]; then \
		latest=$$(ls -t backups/*.dump 2>/dev/null | head -n1); \
		if [ -z "$$latest" ]; then echo "No backups found in ./backups"; exit 1; fi; \
		file=$$(basename "$$latest"); \
		echo "No FILE= given — using most recent backup: $$file"; \
	fi; \
	read -p "Restore $$file into the current PROD database? This overwrites all data. [y/N] " confirm; \
	if [ "$$confirm" != "y" ] && [ "$$confirm" != "Y" ]; then echo "Aborted."; exit 1; fi; \
	cat "backups/$$file" | $(COMPOSE_PROD) exec -T postgres sh -c 'pg_restore --clean --if-exists --no-owner -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

.PHONY: all docker-env var \
        docker-build docker-build-nc docker-run docker-up docker-down docker-down-v \
        docker-restart docker-ps docker-logs docker-logs-django docker-logs-celery \
        docker-shell docker-bash docker-console docker-migrate docker-fakemigrate \
        docker-commit docker-mergemigrations docker-createsuperuser docker-test \
        docker-db-backup docker-db-list docker-db-restore \
        docker-prod-build docker-prod-build-nc docker-prod-run docker-prod-up \
        docker-prod-down docker-prod-down-v docker-prod-restart docker-prod-ps \
        docker-prod-logs docker-prod-shell docker-prod-bash docker-prod-console \
        docker-prod-migrate docker-prod-fakemigrate docker-prod-commit \
        docker-prod-mergemigrations docker-prod-createsuperuser \
        docker-prod-db-backup docker-prod-db-list docker-prod-db-restore
