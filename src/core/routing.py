"""
WebSocket-маршруты проекта, подключаемые в core/asgi.py.
"""

from django.urls import re_path

from apps.notifications.consumers import NotificationConsumer

websocket_urlpatterns = [
    # Под префиксом ws/ - в проде nginx проксирует именно этот префикс на
    # отдельный ASGI-контейнер django-ws (см. docker-compose.prod.yml).
    re_path(r"^ws/notifications/$", NotificationConsumer.as_asgi()),
]
