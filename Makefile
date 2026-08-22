.PHONY: dev-build dev-up dev-down dev-logs \
        prod-build prod-up prod-down \
        backup restore logs-django logs-celery logs-follow \
        migrate createsuperuser test shell

COMPOSE_DEV  = docker compose -f docker-compose.yml --env-file .env
COMPOSE_PROD = docker compose -f docker-compose.prod.yml --env-file .env

# --- DEV ---

dev-build:
	$(COMPOSE_DEV) build

dev-up:
	$(COMPOSE_DEV) up -d

dev-run:
	$(COMPOSE_DEV) up

dev-down:
	$(COMPOSE_DEV) down

dev-logs:
	$(COMPOSE_DEV) logs -f

# --- PROD ---
# django собирается первым: docker/nginx/Dockerfile делает
# multi-stage COPY --from=geo_tracking-django:prod, поэтому образ
# django обязан существовать до сборки nginx.

prod-build:
	$(COMPOSE_PROD) build django
	$(COMPOSE_PROD) build

prod-up:
	$(COMPOSE_PROD) up -d

prod-down:
	$(COMPOSE_PROD) down

# --- Бэкапы (см. scripts/backup_db.sh и scripts/restore_db.sh) ---

backup:
	$(COMPOSE_DEV) exec django bash /scripts/backup_db.sh

# Использование: make restore FILE=geo_db_20260725_030000.sql.gz
# (файл ищется в ./backups, которая смонтирована в /backup)
restore:
	$(COMPOSE_DEV) exec django bash /scripts/restore_db.sh /backup/$(FILE)

# --- Логи ---

logs-django:
	tail -n 200 -f logs/django/django.log

logs-celery:
	tail -n 200 -f logs/celery/celery.log

logs-follow:
	$(COMPOSE_DEV) logs -f django celery-high celery-low celery-beat

# --- Django-команды ---

commit:
	$(COMPOSE_DEV) exec django python manage.py makemigrations ${app}

migrate:
	$(COMPOSE_DEV) exec django python manage.py migrate

createsuperuser:
	$(COMPOSE_DEV) exec django python manage.py createsuperuser

test:
	$(COMPOSE_DEV) exec django pytest

shell:
	$(COMPOSE_DEV) exec django python manage.py shell

