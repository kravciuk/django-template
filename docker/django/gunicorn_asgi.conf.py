"""Конфигурация Gunicorn (ASGI/UvicornWorker) для WebSocket-контейнера (django-ws).

Отдельно от gunicorn.conf.py, т.к. WS-нагрузка отличается от HTTP:
соединения долгоживущие, дешёвые для event loop и не должны прерываться
плановым перезапуском воркера.
"""

import os

bind = "0.0.0.0:8000"
worker_class = "uvicorn.workers.UvicornWorker"

# WS-соединения дешёвые для event loop — по воркеру на ядро не требуется,
# в отличие от sync-воркеров в gunicorn.conf.py.
workers = int(os.environ.get("GUNICORN_WS_WORKERS", "2"))
timeout = int(os.environ.get("GUNICORN_WS_TIMEOUT", "30"))
graceful_timeout = 30
keepalive = 5

accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info").lower()

# В отличие от gunicorn.conf.py (max_requests=1000) здесь периодический
# рестарт воркеров отключён: он бы обрывал долгоживущие WS-соединения.
max_requests = int(os.environ.get("GUNICORN_WS_MAX_REQUESTS", "0"))
max_requests_jitter = int(os.environ.get("GUNICORN_WS_MAX_REQUESTS_JITTER", "0"))
