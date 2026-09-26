# WebSockets (Django Channels)

## Routing

`core/asgi.py`:

```python
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        AuthMiddlewareStack(JWTAuthMiddleware(URLRouter(websocket_urlpatterns)))
    ),
})
```

`core/routing.py` registers exactly one route: `ws/notifications/` → `apps.notifications.consumers.NotificationConsumer`.
In prod, `/ws/` is proxied by nginx to a **separate** `django-ws` container (see
[architecture/docker-topology.md](../architecture/docker-topology.md)); in dev the same single container serves
both HTTP and WS.

## Auth stack

`AuthMiddlewareStack` resolves `scope["user"]` from the session cookie first (free for the browser client).
`JWTAuthMiddleware` (`apps/notifications/ws_auth.py`) sits **inside** that stack and only runs when the session
left `scope["user"]` anonymous/unset:

1. Extracts `token` from the raw query string (`?token=<access token>`).
2. Validates it via SimpleJWT's `AccessToken(token)` (signature + expiry checked here).
3. On success, looks up the user by `access_token["user_id"]`; on any failure (invalid/expired token, user
   deleted), leaves `scope["user"] = AnonymousUser()`.

**It does not close the connection itself** on a bad token — it just leaves the user anonymous and lets the
consumer decide. The actual rejection happens one layer up, in `NotificationConsumer.connect()`:

```python
if self.scope.get("user") is None or self.scope["user"].is_anonymous:
    self.close(code=4401)
    return
```

No error message is echoed back to the client — the handshake either succeeds or the client sees a bare `4401`
close code.

## Consumer (`apps/notifications/consumers.py`)

Push-only: server → client, the client never sends anything over this socket (history/read-state go through the
REST API instead). On connect, joins the Channels group `notifications.user.<user_id>` (`realtime.py`) — keyed by
numeric PK, so no cross-user group collision as long as `user.id` is trustworthy (it is, coming from either
validated session or validated JWT). `disconnect()` only calls `group_discard` if a group was actually joined
(guards against a disconnect firing before `connect()` finished).

## Server → client push (`apps/notifications/realtime.py`)

```python
def push_notification(notification):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return  # mis-configured CHANNEL_LAYERS — notification still exists in the DB/REST API
    async_to_sync(channel_layer.group_send)(group_name_for(notification.recipient_id),
                                             {"type": "notification.push", "payload": NotificationSerializer(notification).data})
```

Payload shape is exactly the REST `NotificationSerializer` output. `NotificationSerializer` is imported inside the
function body specifically to avoid a `serializers → models → realtime → serializers` circular import.

## Browser client (`static/notifications/js/notifications.js`)

```javascript
new WebSocket((location.protocol === "https:" ? "wss:" : "ws:") + "//" + location.host + "/ws/notifications/")
```

**No `?token=` is ever appended by the shipped browser client** — it authenticates purely via the session cookie
through `AuthMiddlewareStack`. The JWT query-param fallback exists for a hypothetical non-browser client, not for
anything currently shipped. This matters for a related nginx-logging concern — see
[security-considerations.md](../security-considerations.md#sec-7-jwt-in-websocket-query-string-would-hit-nginx-access-logs).

Reconnect: flat 3-second retry on `onclose`, no backoff/jitter/cap, **except** it does not retry after a `4401`
close (re-authenticating won't help without a fresh login). Fine at current single-user scale; a thundering-herd
concern at real multi-user scale during an outage.
