"""JWT fallback for WebSocket auth.

core/asgi.py wraps the websocket router in channels.auth.AuthMiddlewareStack,
which resolves scope["user"] from the Django session cookie - that covers
the browser client for free. This middleware sits *inside* that stack (see
core/asgi.py) and only runs when the session left scope["user"] anonymous:
it then looks for a `?token=<access token>` query parameter and validates it
the same way rest_framework_simplejwt validates a normal API request,
letting a non-browser client (no cookie) authenticate the same connection.
"""

from urllib.parse import parse_qs

from asgiref.sync import sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken


@sync_to_async
def _user_from_token(token):
    try:
        access_token = AccessToken(token)
    except TokenError:
        return AnonymousUser()

    User = get_user_model()
    try:
        return User.objects.get(pk=access_token["user_id"])
    except User.DoesNotExist:
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        user = scope.get("user")
        if user is None or user.is_anonymous:
            query_string = scope.get("query_string", b"").decode()
            token = parse_qs(query_string).get("token", [None])[0]
            if token:
                scope["user"] = await _user_from_token(token)
        return await super().__call__(scope, receive, send)
