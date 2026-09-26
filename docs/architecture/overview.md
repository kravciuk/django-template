# Architecture overview

## Tech stack

| Layer | Choice |
|---|---|
| Language / framework | Python 3.14, Django (latest, unpinned — see [operations/running-the-project.md](../operations/running-the-project.md)) |
| Database | PostgreSQL + PostGIS (`django.contrib.gis.db.backends.postgis`), pooled through PgBouncer in prod |
| Cache/broker | Redis (Celery broker/result backend + Channels layer; a second logical DB `REDIS_CACHE_URL` is defined in `.env.example` but **never referenced by any setting** — see [Known Issues](../known-issues.md)) |
| Async/WebSocket | Django Channels 4.x, ASGI via `uvicorn` (dev) / `gunicorn -k UvicornWorker` (prod) |
| REST | Django REST Framework, session + DRF token + SimpleJWT auth stacked |
| Background jobs | Celery (`high`/`low` queues) + Celery Beat |
| Rich text | django-ckeditor-5 (widget only, not a storage format — see [data-model.md](data-model.md)) |
| Tagging | django-taggit |
| Tree structure | django-treebeard (materialized path) for `Note` |
| Tables/filtering | django-tables2 + django-filter (documents list) |
| Images | Pillow + pillow-heif (HEIC→JPEG) + django-imagekit (thumbnails) |
| Sanitization | `nh3` (Rust `ammonia` bindings) — HTML allowlist in `src/libs/html.py` |
| Frontend | Server-rendered Django templates, Bootstrap 5.3.3 (Bootswatch "Flatly" via CDN) + htmx 2.0.4 + a handful of small vanilla-JS progressive-enhancement scripts. No SPA framework, no build step. |

## Django apps and their relationships

```
apps.common        — abstract base models only, no own tables (TimeStampedModel, OwnedModel,
                      PublicIdModel, VisibilityModel, SoftDeleteModel, ExpiryModel) + purge_trash command
apps.users         — custom User model (AUTH_USER_MODEL), JWT token endpoints, login IP/date tracking
apps.content       — Note model (notes / albums / documents / reminders / hidden hub nodes), the core content type
apps.documents      ⤷ a UI layer over Note filtered to kind ∈ {purchase, warranty, contract} — no own model
apps.attachments   — generic file attachments, reusable via GenericForeignKey, used by Note (and by extension Document)
apps.comments      — generic threaded comments, reusable via a small registry, currently wired only to Note
apps.sharing       — ShareLink model + can_view() access-control gate; the redemption *view* does not exist yet
apps.links         — independent bookmarks app (LinkGroup/Link), not integrated with the other content types
apps.notifications — Notification model, Channels consumer, REST API, Celery cleanup job
```

Everything except `apps.links` and `apps.notifications` revolves around `apps.content.Note` plus the two generic
attachments (`Attachment`, `Comment`, `ShareLink`) hanging off it via `GenericForeignKey`. See
[data-model.md](data-model.md) for the exact inheritance/composition of every concrete model.

## Request flow

**Dev** (`docker-compose.yml`): a single `django` container runs `uvicorn core.asgi:application --reload`, serving
HTTP and WebSocket alike (Channels' `ProtocolTypeRouter` dispatches by protocol inside one process). `nginx` sits
in front but only for parity with prod's URL layout — `/static/` is proxied straight back to Django (not aliased,
since a baked static snapshot would go stale immediately against the live-mounted `./src`), `/media/` is aliased
to the same host directory Django writes to, `/ws/` is proxied to the same single Django container.

**Prod** (`docker-compose.prod.yml`): HTTP and WebSocket are split into **two separate containers** from the same
image (`project:prod`): `django` runs `gunicorn --config gunicorn.conf.py core.wsgi:application` (sync workers,
`cpu_count()*2+1`, periodic worker recycling via `max_requests`), and `django-ws` runs
`gunicorn --config gunicorn_asgi.conf.py core.asgi:application` (2 `UvicornWorker`s, `max_requests` disabled since
long-lived WS connections must not be killed by a scheduled recycle). `nginx` proxies `/ws/` to `django-ws` and
everything else to `django`. `RUN_MIGRATIONS=false` is set on `django-ws` specifically so migrations only run once,
from the `django` container's entrypoint, not twice on every deploy.

Both topologies put Postgres behind PgBouncer in prod only; dev connects Django straight to Postgres (see
[docker-topology.md](docker-topology.md) and [settings.md](settings.md)).

## Authentication

Three DRF authentication classes are stacked (`SessionAuthentication`, DRF `TokenAuthentication`,
`rest_framework_simplejwt.JWTAuthentication`), with `IsAuthenticated` as the default permission — every new DRF
view is "must be logged in" unless it opts out explicitly.

There is **no dedicated user-facing login page** — `LOGIN_URL` points at `/admin/login/`
(`core/settings/base.py:131`), used as a deliberate stand-in until `apps.users` grows a real login view. JWT
(`/api/users/token/`, `/api/users/token/refresh/`) exists specifically so the WebSocket auth fallback
(`apps.notifications.ws_auth.JWTAuthMiddleware`) and future non-browser clients have something to authenticate
with — the shipped browser client actually only ever uses the session cookie (see
[api/websockets.md](../api/websockets.md)).

## Cross-cutting patterns worth knowing before touching any app

- **Soft delete is opt-in per model** via `apps.common.models.SoftDeleteModel`, and the manager **does not filter
  trashed rows out by default** — `Model.objects.all()` returns everything, alive and trashed. Every read site is
  expected to call `.alive()` explicitly. See [data-model.md](data-model.md).
- **Public identifiers**: anything reachable by URL uses a random `public_id` (UUID4), never the DB primary key,
  via `apps.common.models.PublicIdModel`.
- **Ownership is single-owner, no ACL**: `apps.common.models.OwnedModel.owner` is a single FK — the codebase
  explicitly rules out a separate ACL/permissions-table system (see model docstring). Sharing beyond the owner is
  meant to go through `apps.sharing`, which is not yet wired up (see [Known Issues](../known-issues.md)).
  Visibility levels (`PUBLIC` / `UNLISTED` / `SHARED` / `PRIVATE`) are the only other access-control axis today.
  Owner filtering is applied per-view, per-queryset (not enforced by a shared row-level-security layer) — this
  matters a great deal once multi-user work starts, see [security-considerations.md](../security-considerations.md).
- **Generic relations, not direct FKs**, connect `Attachment`/`Comment`/`ShareLink` to whatever they're attached
  to — deliberately, to avoid circular package imports and to let new "attachable" models opt in without editing
  the attachment/comment/sharing apps. `apps.comments.registry` is the one place a model has to be explicitly
  registered before its comment thread is reachable by URL.
- **`i18n` is required by project convention** (`gettext_lazy` in models, `gettext` in views, `blocktranslate` in
  templates — see root `CLAUDE.md`) but is **inconsistently applied** across the codebase today — see
  [Known Issues](../known-issues.md#ki-5-missing-i18n-wrapping).
