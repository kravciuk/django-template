import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings.dev")

django_asgi_app = get_asgi_application()

from channels.auth import AuthMiddlewareStack  # noqa: E402
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from apps.notifications.ws_auth import JWTAuthMiddleware  # noqa: E402
from core.routing import websocket_urlpatterns  # noqa: E402

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        # AuthMiddlewareStack resolves scope["user"] from the session cookie
        # (the browser client, for free); JWTAuthMiddleware sits inside it and
        # only runs when that left scope["user"] anonymous, falling back to a
        # ?token=<access token> query param for non-browser clients.
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(JWTAuthMiddleware(URLRouter(websocket_urlpatterns)))
        ),
    }
)
