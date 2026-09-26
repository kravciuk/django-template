# apps.users

Custom `User` model (`AUTH_USER_MODEL`), login-metadata tracking, and JWT token endpoints.

> **Note on `CLAUDE.md`**: the root `CLAUDE.md` describes this app as "an empty scaffold (no models, no views —
> just a placeholder `urls.py`)". That is **no longer accurate** — see [Known Issues](../known-issues.md#ki-1-claudemd-is-out-of-date).

## Model (`models.py`)

`User(AbstractUser)` — the only model:

| Field | Type | Notes |
|---|---|---|
| `json_data` | `JSONField(default=dict, blank=True)` | Freeform, no schema, no readers/writers anywhere yet. |
| `registration_ip` | `GenericIPAddressField(null=True, blank=True)` | **Never set anywhere in the codebase** — see [Known Issues](../known-issues.md#ki-9-registration-ip-and-jwt-login-tracking-gaps). |
| `last_login_ip` | `GenericIPAddressField(null=True, blank=True)` | Set by the `user_logged_in` signal handler (session logins only). |
| `registration_date` | `DateTimeField(auto_now_add=True)` | |
| `last_login_date` | `DateTimeField(null=True, blank=True)` | Same caveat as `last_login_ip`. |

No custom manager/queryset (uses stock `UserManager`). Does not inherit any `apps.common` base — it's the owner
side of every `OwnedModel`, not an owned/trashable object itself.

## Admin (`admin.py`)

`UserAdmin(DjangoUserAdmin)` — extends the stock admin with a read-only "Registration / login metadata" fieldset
(`json_data` + the 4 tracking fields, all read-only — settable only programmatically). No custom `list_display`
or actions beyond Django's defaults.

## URLs (`urls.py`)

```
api/users/token/           TokenObtainPairView   (rest_framework_simplejwt, stock)
api/users/token/refresh/   TokenRefreshView      (stock)
```

One commented-out line (`# path("register/", views.RegisterView...)`) — there is **no `views.py`** in this app
at all, so there is currently no self-registration endpoint. The JWT endpoints exist specifically so
non-browser clients — primarily `apps.notifications.ws_auth.JWTAuthMiddleware`'s `?token=` fallback — have a way
to obtain a token; the shipped browser client authenticates via session cookie instead (see
[api/websockets.md](../api/websockets.md)).

## Signal (`signals.py`)

```python
@receiver(user_logged_in)
def update_last_login_info(sender, request, user, **kwargs):
    user.last_login_date = timezone.now()
    user.last_login_ip = get_client_ip(request)
    user.save(update_fields=[...])
```

Fires only for Django's session-based `login()` (i.e. the admin login page today). **SimpleJWT's
`TokenObtainPairView` never calls `login()`**, so this signal never fires for JWT-only clients — self-documented
in the handler's own docstring as a known gap. `utils.py` just re-exports `libs.utils.get_client_ip` (a generic
helper: reads `X-Forwarded-For` first, falls back to `REMOTE_ADDR`) so this import site keeps working.

## Notable functionality / gaps

- No registration endpoint exists outside Django admin / `manage.py createsuperuser` — consistent with "currently
  single-user," but a real gap for the planned multi-user direction (see
  [future/multi-user-migration.md](../future/multi-user-migration.md)).
- `json_data` is completely schemaless today — future multi-user/personalization work will need to define its
  shape before it becomes an ad hoc dumping ground.
