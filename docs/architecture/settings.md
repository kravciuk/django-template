# Settings

## Layering

`core/settings/base.py` holds everything common. `dev.py` and `prod.py` both do `from .base import *` and
override. `core/settings/local/local.py` layers once more on top of `dev.py` for a single developer's personal
overrides — **not wired up anywhere by default** (not in `manage.py`, `wsgi.py`, `asgi.py`, or
`docker-compose.yml`); to use it you must set `DJANGO_SETTINGS_MODULE=core.settings.local.local` yourself.

All three of `manage.py`, `core/wsgi.py`, `core/asgi.py`, and `core/celery.py` default
`DJANGO_SETTINGS_MODULE` to `core.settings.dev` — prod always sets it explicitly via the `DJANGO_SETTINGS_MODULE`
environment variable in `docker-compose.prod.yml`.

Settings are read from env vars via three small helpers defined at the top of `base.py`: `env(key, default)`,
`env_bool(key, default)` (truthy strings: `1/true/yes/on`), `env_list(key, default, sep=",")`. Nothing is
hardcoded outside of these — check `.env.example` for the full var list before adding a new setting.

## Database

```python
DATABASES["default"] = {
    "ENGINE": "django.contrib.gis.db.backends.postgis",
    "HOST": env("DB_HOST", "pgbouncer"), "PORT": env("DB_PORT", "6432"),
    "CONN_MAX_AGE": 0, "DISABLE_SERVER_SIDE_CURSORS": True,
}
```

`CONN_MAX_AGE=0` and `DISABLE_SERVER_SIDE_CURSORS=True` are both required when sitting behind PgBouncer in
**transaction pooling mode** (`pgbouncer.ini: pool_mode = transaction`) — a persistent Django-side connection or a
server-side cursor would break as soon as PgBouncer hands the underlying connection to a different client between
statements. Dev's actual `.env` overrides `DB_HOST=postgres`/`DB_PORT=5432`, bypassing PgBouncer entirely (dev's
`docker-compose.yml` has no PgBouncer service at all — Django talks straight to Postgres in dev).

## Auth / REST / JWT

- `AUTH_USER_MODEL = "users.User"`.
- `LOGIN_URL = "account_login"` (django-allauth) — see [apps/users.md](../apps/users.md#authentication-django-allauth).
  `AUTHENTICATION_BACKENDS` stacks `ModelBackend` and allauth's own `AuthenticationBackend`. Django admin's own
  login view is also routed through allauth via `admin.site.login = secure_admin_login(admin.site.login)` in
  `core/urls.py`, so 2FA/rate-limiting apply there too — `/admin/login/` isn't a separate, unprotected login path.
- `core/settings/auth.py` (new, imported from `base.py` like `rest.py`/`celery.py`) holds all of allauth's
  settings:
  - `ACCOUNT_LOGIN_METHODS = {"username", "email"}`, `ACCOUNT_UNIQUE_EMAIL=True` (allauth tracks/verifies email in
    its own `EmailAddress` table, not on `User.email` itself).
  - Whether registration is open (`ACCOUNT_ALLOW_SIGNUP`) is a **constance** setting, not a static one here — see
    `core/settings/constance.py` and the "Personal content store settings" table below. Read by
    `apps.users.adapter.AccountAdapter.is_open_for_signup`; see
    [future/multi-user-migration.md](../future/multi-user-migration.md) for what should land before opening it.
  - `ACCOUNT_EMAIL_VERIFICATION = "mandatory"`, `ACCOUNT_SESSION_REMEMBER = None` (shows the "Remember me" checkbox).
  - `ACCOUNT_RATE_LIMITS` — explicit dict (login/signup/password-reset/email-management), backed by `CACHES`
    (below), not django-axes.
  - `MFA_SUPPORTED_TYPES = ["totp", "webauthn", "recovery_codes"]`, `MFA_TOTP_ISSUER` (env).
    `MFA_PASSKEY_LOGIN_ENABLED = True` puts passkeys on the login page itself, not just as 2FA — see
    [apps/users.md](../apps/users.md#authentication-django-allauth).
  - `EMAIL_BACKEND`/`EMAIL_HOST*`/`DEFAULT_FROM_EMAIL` (env) — dev default is the console backend (prints to the
    django container's log), closing [KI-3](../known-issues.md#ki-3-health-check-returns-500).
- `REST_FRAMEWORK`: auth classes = Session, DRF Token, SimpleJWT (in that order); default permission =
  `IsAuthenticated`; pagination = `PageNumberPagination`, `PAGE_SIZE=50`.
- `SIMPLE_JWT`: access token lifetime from `JWT_EXPIRATION` (seconds, default 3600), refresh lifetime 7 days
  fixed (not env-configurable), `ROTATE_REFRESH_TOKENS=True`, `BLACKLIST_AFTER_ROTATION=True`, signing key from
  `JWT_SECRET_KEY` (falls back to `SECRET_KEY` if unset). **`apps.users.urls`'s `token/` endpoint bypasses
  allauth's rate limiting and 2FA entirely** (it authenticates directly against username+password) — see
  [security-considerations.md](../security-considerations.md).

## Celery

`CELERY_BROKER_URL`/`CELERY_RESULT_BACKEND` both default to `redis://redis:6379/0` (same Redis DB as the Channels
layer — see below). `CELERY_DEFAULT_QUEUE_NAME`/`CELERY_HIGH_QUEUE_NAME` just name the two queues; actual queue
wiring and the beat schedule live in `core/celery.py` (see
[background-jobs/celery.md](../background-jobs/celery.md)).

## Channels

```python
CHANNEL_LAYERS = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer",
                               "CONFIG": {"hosts": [env("REDIS_URL", "redis://redis:6379/0")]}}}
```

Same Redis logical DB (`/0`) as Celery's broker — there's no separation between the Channels layer and the
Celery broker traffic on the same Redis instance/DB index.

## CORS

`CORS_ALLOWED_ORIGINS` from `env_list`, empty by default; `CORS_ALLOW_CREDENTIALS=True` always. `dev.py` opens
this up further with `CORS_ALLOW_ALL_ORIGINS=True`. `prod.py` explicitly sets `CORS_ALLOW_ALL_ORIGINS=False`.

## GeoIP2

```python
_geoip_env_path = env("GEOIP_PATH", "/app/geoip")
GEOIP_PATH = str(Path(_geoip_env_path).parent) if _geoip_env_path.endswith(".mmdb") else _geoip_env_path
```

`.env.example` sets `GEOIP_PATH=/app/geoip/GeoLite2-City.mmdb` (a file path); this snippet strips it down to the
containing directory because GeoIP2's Django integration (`django.contrib.gis.geoip2`) wants a directory, not a
file. The actual `.mmdb` file is fetched by `scripts/init_geoip.sh`, driven by the daily Celery Beat task
`core.tasks.update_geoip_database` (see [background-jobs/celery.md](../background-jobs/celery.md)) — **note that
nothing in the current codebase actually queries GeoIP2 at request time** (no middleware populates
`client_ip`/geo fields — see [background-jobs/logging.md](../background-jobs/logging.md)); the infrastructure is
present but unused today.

## Personal content store settings

| Setting | Default | Used by |
|---|---|---|
| `TAGGIT_CASE_INSENSITIVE` | `True` | global taggit behavior |
| `IMAGEKIT_DEFAULT_THUMBNAIL_FORMAT` | `"JPEG"` | forces every generated thumbnail to JPEG regardless of source format — needed because a HEIC "thumbnail" would only render in Safari |
| `CKEDITOR_5_CONFIGS` | two configs: `default`, `content_note` | widget-only; `Note.body`/`Attachment` fields stay plain `TextField`s — the schema never depends on this package. `licenseKey: "GPL"` suppresses CKEditor5's "Powered by" badge (self-hosted GPL use) |
| `ATTACHMENTS_MAX_UPLOAD_SIZE` | 25 MB | per-file cap, `apps/attachments/validators.py` |
| `ATTACHMENTS_ALLOWED_EXTENSIONS` | `[]` (no restriction) | extension whitelist — **empty by default**, see [security-considerations.md](../security-considerations.md) |
| `ATTACHMENTS_MAX_FILES_PER_UPLOAD` | 10 | `apps/content/forms.py::NoteForm.clean_attachments` |
| `DATA_UPLOAD_MAX_MEMORY_SIZE` / `FILE_UPLOAD_MAX_MEMORY_SIZE` | `ATTACHMENTS_MAX_UPLOAD_SIZE × ATTACHMENTS_MAX_FILES_PER_UPLOAD` (≈ 250 MB by default) | sized for a whole multi-file submission, not one file — see [Known Issues](../known-issues.md) for the memory-pressure implication |
| `TRASH_RETENTION_DAYS` | 30 | how long a soft-deleted row survives before `purge_trash` hard-deletes it |
| `DRAFT_RETENTION_DAYS` | 7 | how long an autosaved-but-never-published `Note` draft survives before the daily beat task trashes it |
| `COMMENTS_MAX_DEPTH` | 5 | **also hardcoded as a DB `CheckConstraint`** on `Comment.depth` — raising this setting without a matching migration is a footgun, see [Known Issues](../known-issues.md) |
| `NOTIFICATIONS_RETENTION_DAYS` | 90 | daily beat task hard-deletes **read** notifications older than this (by `created_at`, not `read_at`) |
| `ACCOUNT_ALLOW_SIGNUP` | `False` | whether `/accounts/signup/` is open - read by `apps.users.adapter.AccountAdapter.is_open_for_signup`, see [apps/users.md](../apps/users.md#authentication-django-allauth) |
| `MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN` | `False` | allows WebAuthn (passkeys) over plain http from a non-`localhost` dev host - browser spec otherwise requires a secure context; **never** set in prod |

## Not configured (worth knowing before assuming otherwise)

- **No `HEALTH_CHECK` setting** — `django-health-check`'s defaults are used as-is (checks cache, DB, DNS, mail,
  storage).

`EMAIL_BACKEND`/`EMAIL_HOST` and `CACHES` **are now configured** (`core/settings/auth.py`, added alongside
django-allauth) — see the "Auth / REST / JWT" section above. `CACHES` points at `REDIS_CACHE_URL` (Redis DB `/1`,
previously unused) specifically because `ACCOUNT_RATE_LIMITS` needs a real shared backend, not per-process
`LocMemCache`.

## Logging

`LOGGING_CONFIG = None` in both `dev.py` and `prod.py`; `base.py` builds the dict itself via
`core.logging.get_logging_config()` and calls `logging.config.dictConfig(LOGGING)` at import time (not through
Django's usual settings-driven mechanism). See [background-jobs/logging.md](../background-jobs/logging.md) for
the full pipeline.

## Dev-only settings (`core/settings/dev.py`)

- `DEBUG=True`, `LOG_LEVEL="DEBUG"`.
- `debug_toolbar` conditionally added via `ENABLE_DEBUG_TOOLBAR` (default `True`).
- Explicitly opts the template engine **out** of Django's mandatory `cached.Loader` wrapping (Django always wraps
  the default loaders in `cached.Loader` regardless of `DEBUG` since Django 6 dropped the old debug-gates-caching
  behavior) by spelling out `filesystem.Loader` + `app_directories.Loader` explicitly and setting `APP_DIRS=False`
  (Django forbids combining explicit `loaders` with `APP_DIRS=True`). Without this, an edited template would only
  show up after a full container restart, defeating the whole point of the `./src:/app` live-mount.

## Prod-only settings (`core/settings/prod.py`)

`SECURE_SSL_REDIRECT` (default true, env-overridable), `SESSION_COOKIE_SECURE`/`CSRF_COOKIE_SECURE=True`,
`SECURE_HSTS_SECONDS=7 days` + subdomains + preload, `X_FRAME_OPTIONS="DENY"`,
`SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https")` (required since nginx terminates TLS and forwards
plain HTTP to gunicorn).
