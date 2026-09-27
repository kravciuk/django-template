# apps.users

Custom `User` model (`AUTH_USER_MODEL`), login-metadata tracking, the JWT token endpoints, and the human-facing
profile page. All of login/logout/signup/password-reset/2FA is handled by django-allauth, wired in via
`core/settings/auth.py` and `core/urls.py` — not by anything in this app's own views.

## Authentication (django-allauth)

Login/logout/signup/password-reset/2FA all live under `/accounts/` (`allauth.urls`, included in `core/urls.py`
inside `i18n_patterns` so these pages get a language prefix like the rest of the human-facing UI). `LOGIN_URL =
"account_login"`. Django admin's own login is routed through the same flow —
`admin.site.login = secure_admin_login(admin.site.login)` in `core/urls.py` — so 2FA/rate-limiting apply there
too; `/admin/login/` is not a separate unprotected path.

- **Login**: by username or email (`ACCOUNT_LOGIN_METHODS`), with a "Remember me" checkbox
  (`ACCOUNT_SESSION_REMEMBER = None`).
- **Registration**: closed by default (`ACCOUNT_ALLOW_SIGNUP`, a **constance** setting —
  `core/settings/constance.py`, toggled at `/admin/constance/config/`, no redeploy needed) —
  `apps.users.adapter.AccountAdapter.is_open_for_signup` reads it via `from constance import config`. See
  [future/multi-user-migration.md](../future/multi-user-migration.md) for what should land before opening it for
  real (SSRF in the favicon fetcher, the global tag autocomplete, `apps.sharing`). When open, signup requires
  email confirmation (`ACCOUNT_EMAIL_VERIFICATION = "mandatory"`) — allauth tracks/verifies email in its own
  `EmailAddress` table (`ACCOUNT_UNIQUE_EMAIL = True`), not on `User.email` itself.
- **2FA**: TOTP + recovery codes (`MFA_SUPPORTED_TYPES`), managed at `/accounts/2fa/`.
- **Rate limiting**: `ACCOUNT_RATE_LIMITS` (core/settings/auth.py), backed by `CACHES` (Redis, `REDIS_CACHE_URL`)
  — not django-axes. A brute-forced login gets a normal 200 + form error ("Too many failed login attempts"), not
  a 429 — that status only applies to views that call allauth's `consume_or_429` directly (signup, password
  reset).
- **Email**: sent synchronously via `EMAIL_BACKEND` (env; dev default is the console backend, printing to the
  django container's log) — there's no Celery worker in dev to route it through, see root `CLAUDE.md`.
- Templates: `src/templates/allauth/layouts/base.html` (extends the project's own `base.html`) and
  `src/templates/allauth/elements/*.html` re-skin every allauth page (login, signup, password reset, email
  management, 2FA) in the project's Bootstrap/Flatly style instead of allauth's bare default markup — see the
  comments in those files for the slot/element mechanics.
- Tests: `tests/unit/test_auth.py`.

**JWT endpoints below bypass all of this** (no rate limiting, no 2FA) — see "URLs" below.

## Model (`models.py`)

`User(AbstractUser)` — the only model:

| Field | Type | Notes |
|---|---|---|
| `json_data` | `JSONField(default=dict, blank=True)` | Freeform, no schema, no readers/writers anywhere yet. |
| `registration_ip` | `GenericIPAddressField(null=True, blank=True)` | Set by `apps.users.signals.record_registration_ip` (allauth's `user_signed_up` signal) — only fires for users created through the allauth signup form, not `createsuperuser`/admin-created users. |
| `last_login_ip` | `GenericIPAddressField(null=True, blank=True)` | Set by the `user_logged_in` signal handler (session logins only). |
| `registration_date` | `DateTimeField(auto_now_add=True)` | |
| `last_login_date` | `DateTimeField(null=True, blank=True)` | Same caveat as `last_login_ip`. |

No custom manager/queryset (uses stock `UserManager`). Does not inherit any `apps.common` base — it's the owner
side of every `OwnedModel`, not an owned/trashable object itself.

`migrations/0002_backfill_email_addresses.py` is a data-only migration (no schema change) that creates a
verified, primary allauth `EmailAddress` for every pre-existing user with a non-empty email — otherwise the
existing owner couldn't log in by email once `ACCOUNT_EMAIL_VERIFICATION="mandatory"` took effect.

## Admin (`admin.py`)

`UserAdmin(DjangoUserAdmin)` — extends the stock admin with a read-only "Registration / login metadata" fieldset
(`json_data` + the 4 tracking fields, all read-only — settable only programmatically). No custom `list_display`
or actions beyond Django's defaults.

## URLs

```
accounts/...                  allauth.urls (login/logout/signup/password reset/2FA - see above)
accounts/profile/              users.page_urls -> ProfileUpdateView (first/last name only)
api/users/token/               TokenObtainPairView   (rest_framework_simplejwt, stock)
api/users/token/refresh/       TokenRefreshView      (stock)
```

`urls.py` (the JWT api, `app_name = "users_api"`) and `page_urls.py` (the human-facing profile page,
`app_name = "users"`) are deliberately separate modules with different `app_name`s — reusing one `app_name` for
both trips Django's `urls.W005` "namespace isn't unique" system check even though the individual url names don't
collide. `page_urls.py` needs the i18n prefix the other human-facing apps get (see `core/urls.py`); the JWT api
is machine-consumed and stays unprefixed.

The JWT endpoints exist specifically so a non-browser client — primarily
`apps.notifications.ws_auth.JWTAuthMiddleware`'s `?token=` fallback — has a way to obtain a token; the shipped
browser client authenticates via session cookie instead (see [api/websockets.md](../api/websockets.md)). **They
bypass allauth's rate limiting and 2FA entirely** (`TokenObtainPairView` authenticates directly against
username+password) — see [security-considerations.md](../security-considerations.md).

## Signals (`signals.py`)

```python
@receiver(user_logged_in)
def update_last_login_info(sender, request, user, **kwargs): ...

@receiver(user_signed_up)  # allauth.account.signals
def record_registration_ip(sender, request, user, **kwargs): ...
```

`update_last_login_info` fires for any session-based `django.contrib.auth.login()` call, which includes
allauth's own login view. **SimpleJWT's `TokenObtainPairView` never calls `login()`**, so this signal never fires
for JWT-only clients — self-documented in the handler's own docstring as a known gap. `utils.py` just re-exports
`libs.utils.get_client_ip` (a generic helper: reads `X-Forwarded-For` first, falls back to `REMOTE_ADDR`) so this
import site keeps working.

## Notable functionality / gaps

- `json_data` is completely schemaless today — future multi-user/personalization work will need to define its
  shape before it becomes an ad hoc dumping ground.
- `registration_ip` is still `null` for every user created outside the allauth signup form (admin, `createsuperuser`) —
  expected, not a bug.
