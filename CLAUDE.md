# CLAUDE.md

Общее описание проекта: /home/vadim/web/django-template/.llm/content.md

Full architecture/per-app/API/known-issues documentation: **[`docs/README.md`](docs/README.md)** — read that
first for anything beyond a quick fact-check; this file only covers cross-cutting conventions and commands.

## What this is

A Dockerized Django app (GeoDjango/PostGIS + REST + JWT + Channels + Celery) implementing a **personal
document/notes/link store with warranty and contract deadline tracking**. Currently single-user (one owner via
Django admin/`createsuperuser`); a move to multi-user is planned — see
[`docs/future/multi-user-migration.md`](docs/future/multi-user-migration.md) for what that touches.

Apps under `src/apps/` (one page each under [`docs/apps/`](docs/apps/)):

| App | What it is |
|---|---|
| `common` | Abstract base models only (soft-delete/trash, ownership, visibility, public UUIDs, expiry dates) — no own tables/migrations. |
| `users` | Custom `User` model, JWT token endpoints, login IP/date tracking. **Not an empty scaffold** — has real models/admin/signals. |
| `content` | `Note` — the core polymorphic model (notes, albums, documents, reminders, hidden hub nodes), treebeard tree. |
| `documents` | UI layer over `Note` filtered to purchase/warranty/contract kinds — no model of its own. |
| `attachments` | Generic file uploads (HEIC→JPEG, thumbnails, size/extension limits), attached via `GenericForeignKey`. |
| `comments` | Generic depth-limited threaded comments, reusable via a small registry. |
| `sharing` | `ShareLink` model + `can_view()` access gate — **the redemption view doesn't exist yet**, so `Visibility.SHARED` is currently unreachable. |
| `links` | Independent bookmarks dashboard with server-side favicon fetching. |
| `notifications` | In-app notification inbox delivered live over a Channels WebSocket + REST API + Celery cleanup job. |
| `events` | `/events/` calendar (FullCalendar, mobile-friendly) over `Note` — no models. Quick notes (`NoteKind.EVENT`) under a hidden hub node, recurrence (RRULE), per-note colors (defaults in constance), reminders via `notifications`. |

All Django code lives under `src/` (that's the `pythonpath` for pytest and the Docker build context subdir). There
is no top-level `manage.py` — it's at `src/manage.py`.

Before assuming something is missing/broken, check [`docs/known-issues.md`](docs/known-issues.md) and
[`docs/security-considerations.md`](docs/security-considerations.md) — most non-obvious gaps found by review are
already catalogued there with file/line references, instead of repeated here.

## Commands

Everything runs through Docker Compose via the `Makefile`; there's no local venv workflow. Dev containers mount
`./src` live, so no rebuild is needed after editing Python files — only after changing dependencies or the Dockerfile.

```bash
make docker-build       # build dev images (django first, then the rest — see docker-topology.md)
make docker-up          # start dev stack detached (postgres, redis, django, nginx)
make docker-run         # same, attached (see logs in foreground)
make docker-down        # stop dev stack
make docker-down-v      # stop dev stack AND drop named volumes (postgres/redis data!)

make docker-migrate app=content      # python manage.py migrate (omit app= for everything)
make docker-commit app=content       # python manage.py makemigrations content
make docker-createsuperuser
make docker-shell                    # django shell
make docker-bash                     # bash inside the django container
make docker-console app="some_command --flag"
make docker-test                     # pytest, inside the django container
make docker-restart service=django   # omit service= to restart everything
make docker-ps
make docker-logs service=django      # omit service= to follow every container

make docker-logs-django   # tail logs/django/django.log
make docker-logs-celery   # tail logs/celery/celery.log

make docker-db-backup                       # pg_dump -Fc run inside the postgres container itself -> backups/*.dump
make docker-db-list                         # list ./backups/*.dump, most recent first
make docker-db-restore FILE=backup_*.dump   # restores a specific backup (confirmation prompt);
                                             # omit FILE= to restore the most recent one instead
                                             # (this is the only backup/restore mechanism now — the old
                                             # scripts/backup_db.sh + Celery task were removed, see below)

make docker-prod-build  # builds django image first, then the rest (nginx's
                         # Dockerfile does COPY --from=project:prod,
                         # so django must exist before nginx builds — plain
                         # `docker compose build` does not guarantee this order)
make docker-prod-up / docker-prod-down
```

Every dev target above has a `docker-prod-*` twin running against `docker-compose.prod.yml` (e.g.
`docker-prod-migrate`, `docker-prod-db-restore`) — see the `Makefile` for the full list. `docker-prod-test` does
not exist (`pytest` is dev-only). Full command reference:
[`docs/operations/running-the-project.md`](docs/operations/running-the-project.md).

To run a single test or pass extra pytest args:

```bash
make docker-test args="tests/unit/test_x.py::test_it -v"
```

Test settings: `pytest.ini` (project root) sets `DJANGO_SETTINGS_MODULE=core.settings.dev`, `pythonpath=src`,
`testpaths=tests`, `python_files=test_*.py` — so tests live under the top-level `tests/unit/`/`tests/integration/`
as `test_*.py` (a per-app `tests_*.py` file would not be collected by pytest). ~217 tests, all passing — see
[`docs/operations/testing.md`](docs/operations/testing.md) for what's covered per app and known gaps (notably
`apps.documents` has no dedicated test file yet).

There is no linter/formatter config in the repo (no ruff/flake8/black config) — don't assume one.

## Settings layering

`core/settings/base.py` holds everything common; `dev.py` and `prod.py` do `from .base import *` and override.
`core/settings/local/local.py` layers once more on top of `dev.py` for one developer's personal overrides — not
wired up anywhere by default (must set `DJANGO_SETTINGS_MODULE=core.settings.local.local` explicitly to use it).
`DJANGO_SETTINGS_MODULE` defaults to `core.settings.dev` in `manage.py`, `wsgi.py`, `asgi.py`, and `celery.py` —
prod always sets it explicitly via env (`docker-compose.prod.yml`, `Dockerfile.prod`). All settings are read from
env vars via the `env`/`env_bool`/`env_list` helpers at the top of `base.py`, not hardcoded — check `.env.example`
for the full var list before adding a new setting. Full per-setting reference:
[`docs/architecture/settings.md`](docs/architecture/settings.md).

Dev vs prod topology differs, not just settings values:
- **Dev** (`docker-compose.yml`): `postgres`, `redis`, `django` (uvicorn, not `runserver` — Channels 4.x has no
  ASGI `runserver` variant), `nginx`. No PgBouncer, no Celery workers/beat in dev — Django connects straight to
  Postgres (`DB_HOST`/`DB_PORT` in `.env`).
- **Prod** (`docker-compose.prod.yml`): adds `pgbouncer` (Django's actual DB host/port in prod), a separate
  `django-ws` container (ASGI, for `/ws/` only — see below), `celery-high`, `celery-low`, `celery-beat`, and
  `nginx` (terminates HTTP, proxies `/ws/` to `django-ws` and `/` to `django`'s gunicorn, serves `/static/` and
  `/media/` directly). Prod containers read env from `.env.prod`, not `.env`.

Full container-by-container breakdown: [`docs/architecture/docker-topology.md`](docs/architecture/docker-topology.md).

Time zones: the DB always stores UTC (`TIME_ZONE = "UTC"`, `USE_TZ`); each user's profile `User.timezone` is
activated per request by `apps.users.middleware.UserTimezoneMiddleware`, so forms/templates/the calendar show local
wall-clock time. Background code formatting a time for a user must use `apps.users.middleware.user_zoneinfo()`
— there's no request there. Date/time *display formats* are per user too (`User.date_format`/`time_format`,
blank = the language's Django formats): in templates use the `user_formats` filters (`|user_date`,
`|user_datetime`, `|user_time`) instead of `|date:"SHORT_*"`, in background code
`apps.users.formats.format_date/format_datetime(value, user=...)`, and include
`includes/_date_inputs.html` on any page with a date input — see [`docs/apps/users.md`](docs/apps/users.md).

## Celery

`core/celery.py` defines the app with two queues, `high` and `low` (default). Routing is by task name suffix:
anything named `*.high_priority_task` goes to `high`; everything else goes to `low` (nothing currently uses that
suffix, so every task runs on `low` today). Beat schedule (same file) runs, daily: `core.tasks.update_geoip_database`
(03:00), `apps.content.tasks.cleanup_stale_drafts` (02:00), `apps.notifications.tasks.cleanup_old_notifications`
(04:00), `apps.links.tasks.refetch_missing_favicons` (05:00, retries links still without a favicon); and every 5 minutes `apps.events.tasks.send_due_reminders` (calendar/document reminders — after first
deploying it, run `manage.py refresh_event_reminders` once so existing documents get a `remind_at`). `core.tasks.update_geoip_database` just shells out to `scripts/init_geoip.sh` via `subprocess.run` and
raises `RuntimeError` on non-zero exit; the script is copied into the image at `/scripts` (see Dockerfiles), not
run from the repo path directly.

There used to be a fourth beat task, `core.tasks.backup_database` (daily 00:00, driving
`scripts/backup_db.sh`/`restore_db.sh`) — both the task and the scripts were **removed**: `pg_dump` run from the
django image (`postgresql-client` apt package, v17) was a major version behind `postgis/postgis:18-3.6` and
silently produced empty backup files every time. Manual backup/restore now goes through
`make docker-db-backup`/`docker-db-restore` (above), which run `pg_dump -Fc`/`pg_restore` *inside* the `postgres`
container itself instead — no automated daily backup exists today; see
[`docs/known-issues.md`](docs/known-issues.md) for the history if this surfaces again.

`apps.common`'s `purge_trash` management command (hard-deletes anything past `TRASH_RETENTION_DAYS`) is **not**
on this schedule either — it's manually/cron-invoked only. Full task reference:
[`docs/background-jobs/celery.md`](docs/background-jobs/celery.md).

## GeoDjango / Channels

- DB engine is `django.contrib.gis.db.backends.postgis` — this is a GeoDjango project; GDAL/PROJ system libs are
  installed in both Dockerfiles for this reason. **Nothing in the app currently queries GeoIP2 at request time** —
  the infrastructure (daily DB download, `GEOIP_PATH` setting) is present but unused.
- `GEOIP_PATH` in settings is derived from the `GEOIP_PATH` env var: if that env var ends in `.mmdb`, settings
  strips it down to the containing directory (GeoIP2's Django integration wants a dir, not a file path).
- `core/asgi.py` wires up Channels (`ProtocolTypeRouter` with `AllowedHostsOriginValidator` +
  `AuthMiddlewareStack` + `apps.notifications.ws_auth.JWTAuthMiddleware` + `URLRouter`). `core/routing.py`
  (`websocket_urlpatterns`) now registers one route, `ws/notifications/` →
  `apps.notifications.consumers.NotificationConsumer` — it's no longer empty; add new consumers there. Full
  routing/auth detail: [`docs/api/websockets.md`](docs/api/websockets.md).

## REST / auth

DRF is configured with three auth backends stacked (session, DRF token, SimpleJWT) and `IsAuthenticated` as the
default permission — new views inherit "must be logged in" unless they explicitly opt out. JWT lifetime comes from
`JWT_EXPIRATION` (access) with rotating refresh tokens and blacklist-after-rotation enabled (note:
`rest_framework_simplejwt.token_blacklist` isn't actually installed — see
[`docs/security-considerations.md`](docs/security-considerations.md)). Full endpoint list:
[`docs/api/rest-endpoints.md`](docs/api/rest-endpoints.md).

User-facing login/logout/signup/password-reset/2FA is django-allauth, under `/accounts/` — `LOGIN_URL =
"account_login"`, and `/admin/login/` is routed through the same flow (`secure_admin_login` in `core/urls.py`),
not a separate unprotected page. Registration is closed by default (`ACCOUNT_ALLOW_SIGNUP`, a runtime constance
setting — `/admin/constance/config/`, not an env var). All the
`ACCOUNT_*`/`MFA_*` settings live in `core/settings/auth.py`. See
[`docs/apps/users.md`](docs/apps/users.md#authentication-django-allauth).


### Tests

Per-app tests live in a `tests/` package (`src/apps/<app>/tests/`, with `__init__.py`), not a single
flat `tests.py` — a monolithic file mixing unrelated cases becomes unmanageable as an app grows.
Split by topic/feature, one file per `TestCase`-sized concern, named `tests_<topic>.py` (e.g.
`tests_credit_note_cases.py`, `tests_payout_batch.py`), each importing only what it needs. Django's
default `DiscoverRunner` finds any `test*.py` file recursively, so no extra settings are needed for
the nested package. When adding tests to an app that still has a flat `tests.py`, migrate it to a
`tests/` package as part of the change rather than appending to the monolith.

### Django admin

Standard for every `admin.py`. Legacy files (`repairs`, `blog`, `tech_tasks`, `account`, `faq`,
`cars`) don't follow it yet — when touching one, bring the code you change up to it rather than
copying the old style.

- **Actions are `@admin.action` methods** on the ModelAdmin, listed in `actions` by name as strings
  (`actions = ["generate_pdf_zip", "mark_as_paid"]`). Set `description` / `permissions` through the
  decorator — never `func.short_description = ...` or `func.allowed_permissions = ...`. A
  module-level action function is allowed only when several different ModelAdmins really share
  it; then it lives in a shared module or mixin and is still decorated. Same for columns:
  `@admin.display(...)`, not `.short_description` / `.boolean` attributes.
- Wrap every `description` in `gettext_lazy` (`_()`).
- **Place a helper by what it depends on**, not at module level by default:
  - uses `request`, `self.model`, `self.message_user`, formsets → method of the ModelAdmin/Inline
    (private ones prefixed `_`);
  - needed by two admin classes (e.g. a ModelAdmin and its Inline) → a mixin in the same `admin.py`;
  - pure logic that knows nothing about admin or request (rounding, sign flips, period lists) →
    `<app>/utils.py`;
  - a business rule about a model → a model method or `<app>/utils.py`, never `admin.py`.
  Don't use `@staticmethod` just to tuck a pure utility into an admin class. Module-level
  constants are fine.
- Forms go to `<app>/forms.py`, not `admin.py`.
- **File order:** imports, logger, constants → list filters, inlines, mixins → `@admin.register`
  classes. **Inside a ModelAdmin:** `form` / `Media` / declarative attributes → Django hook
  overrides (`get_*`, `save_*`, `has_*_permission`, `get_urls`) → `@admin.display` methods →
  `@admin.action` methods → custom views → private `_` helpers.
- Moving an action from a function to a method is behavior-neutral only if the name stays the same
  (it is the `action` value in the changelist POST). When moving helpers out of `admin.py`, update
  test imports (`from <app>.admin import ...`) and `mock.patch("<app>.admin.<name>")` targets.

### i18n

The project ships in 7 languages (`core/settings/regional.py`'s `LANGUAGES`), English as the
default/unprefixed one. Source strings are always written in English — **every** user-facing
string must be wrapped for translation, not just the ones a feature happens to touch:

- **Templates:** `{% load i18n %}` + `{% translate "…" %}` for a plain string, `{% blocktranslate %}`
  for one with a variable (with `count`/`{% plural %}` for anything pluralized) — never build a
  user-facing string by concatenating `{% translate %}` output with plain template text.
- **Models:** `verbose_name`, `verbose_name_plural`, `help_text`, and every `TextChoices`/
  `IntegerChoices` label go through `gettext_lazy as _` (evaluated at class-definition time, so it
  must stay lazy, not `gettext`). Same for form field `label`/`help_text` and admin
  `@admin.display`/`@admin.action` `description=`.
- **Views/runtime messages** (`messages.success`, raised `ValidationError`, etc.): `gettext`
  (`django.utils.translation.gettext`, not the lazy variant — these run per-request, after the
  active language is already resolved).
- **Plurals:** `ngettext`/`ngettext_lazy`, never hand-rolled `if count == 1`.
- **JS:** `gettext()`/`interpolate()` from the `JavaScriptCatalog` view (`jsi18n/` in `core/urls.py`,
  loaded once in `templates/base.html`) — don't hardcode UI strings in `.js` files.
- Never hardcode a locale code (`"ru"`, `lang="ru"`, `Intl.RelativeTimeFormat("ru")`, …) or a fixed
  date format (`date:"d.m.Y"`) — use `{% get_current_language %}`/`document.documentElement.lang`
  and Django's locale-aware format names (`SHORT_DATE_FORMAT`, `SHORT_DATETIME_FORMAT`) instead, so
  the result follows the active language.
- Log messages (`logger.info`/`.error`/…) are plain English, not translated — they're for whoever
  reads the logs, not the end user.
- Changing a model's choices labels (e.g. wrapping them in `gettext_lazy`) changes that field's
  migration state — run `makemigrations` for the affected app and check in the (metadata-only, no
  schema/data change) migration; see "model structure" below.
- No `.po`/`.mo` files exist yet (`src/locale/` is an empty target dir) — actual translation of the
  wrapped strings into the 6 non-English languages is a separate, not-yet-done step.



### Instructions

- All code and code comments are in English only.
- If a question is asked, answer in the language it was asked in. Do not make any code or changes to the question.
- Do not perform any git actions unless directly instructed.
- If you're going to make changes to the model structure that will require migrations, always ask permission and explain the reason.
- Never force-push (`--force`/`--force-with-lease`) to `master`, under any circumstance — it is a shared branch and rewriting its history breaks it for everyone. On other branches, before running or suggesting a force-push, warn about the consequences: rewriting history on a shared feature branch invalidates commit hashes anyone else already pulled, so their next `git pull` diverges and can produce merge conflicts even with no real local changes of their own (identical content ends up on two different commit hashes because it was rebased onto a different base). Prefer `--force-with-lease` over plain `--force`, and note that a colleague who has the old branch checked out should reset to the new remote tip (e.g. `git reset --hard origin/<branch>`) rather than merge.
- Before running `git push --force`/`--force-with-lease` on a branch, or suggesting one, warn about the consequences: rewriting history on a shared feature branch invalidates commit hashes anyone else already pulled, so their next `git pull` diverges and can produce merge conflicts even with no real local changes of their own (identical content ends up on two different commit hashes because it was rebased onto a different base). Prefer `--force-with-lease` over plain `--force`, and note that a colleague who has the old branch checked out should reset to the new remote tip (e.g. `git reset --hard origin/<branch>`) rather than merge.
