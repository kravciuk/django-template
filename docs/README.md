# Project documentation

This is a from-scratch technical review of the codebase as it actually exists today (2026-09-26), written so an
AI coding agent or a new contributor can get oriented without reading every file first. It documents what is
actually implemented — not the aspirational template description in the root `CLAUDE.md` (see
[Known Issues #1](known-issues.md#ki-1-claudemd-is-out-of-date) for how far that has drifted).

## What this project actually is

Despite the generic "GeoDjango geo-tracking template" framing in the root `CLAUDE.md`, the codebase has been
built out into a **personal document/notes/link store with warranty and contract deadline tracking**:

- **Notes** (`apps.content`) — a tree of freeform notes (plain notes, photo albums, purchase records, warranties,
  contracts, reminders, hidden "hub" nodes), all backed by one polymorphic `Note` model.
- **Documents** (`apps.documents`) — a filtered view of the same `Note` model (kind ∈ purchase/warranty/contract)
  with an expiry date, used for contract/warranty deadline tracking.
- **Attachments** (`apps.attachments`) — generic file uploads (images auto-converted from HEIC, thumbnails,
  size/extension limits) attachable to any model via a generic relation.
- **Comments** (`apps.comments`) — a generic, depth-limited threaded comment system attachable to any model.
- **Sharing** (`apps.sharing`) — data model and access-control logic for public share links (token + optional
  password + expiry/usage caps). **Not wired up to a URL yet** — see
  [Known Issues](known-issues.md) / [Security Considerations](security-considerations.md).
- **Links** (`apps.links`) — a personal bookmarks dashboard, grouped, drag-and-drop reorderable, with
  server-side favicon fetching.
- **Notifications** (`apps.notifications`) — an in-app notification inbox delivered live over a Django Channels
  WebSocket, plus a REST API and a Celery-beat retention job.
- **Users** (`apps.users`) — a custom `User` model with login IP/date tracking, JWT issuance for non-browser
  clients (used by the WebSocket auth fallback).
- **Common** (`apps.common`) — shared abstract base models: soft-delete/trash, ownership, visibility, public
  UUIDs, expiry dates — reused across every other app.

It is currently **single-user** (one owner per install, via Django admin / `createsuperuser`), and the project is
explicitly planned to move to a **multi-user** model. Several documents here flag exactly which corners were cut
because of that assumption (see [Security Considerations](security-considerations.md)).

## How to use this documentation

Start with [`architecture/overview.md`](architecture/overview.md) for the system map, then drill into the app you
care about under [`apps/`](apps/). [`known-issues.md`](known-issues.md) and
[`security-considerations.md`](security-considerations.md) consolidate every concrete bug/gap found during this
review, cross-referenced from the per-app docs instead of repeated in them.

| Section | Contents |
|---|---|
| [`architecture/overview.md`](architecture/overview.md) | System map, tech stack, request flow, app dependency graph |
| [`architecture/data-model.md`](architecture/data-model.md) | `apps.common` abstract base classes and how every concrete model composes them |
| [`architecture/settings.md`](architecture/settings.md) | Every setting, env var, and settings-layering rule |
| [`architecture/docker-topology.md`](architecture/docker-topology.md) | Dev vs. prod container topology, build order, volumes |
| [`apps/*.md`](apps/) | One file per Django app: models, views, business logic, notable behavior |
| [`api/rest-endpoints.md`](api/rest-endpoints.md) | Every DRF endpoint, auth/permission scheme |
| [`api/websockets.md`](api/websockets.md) | Channels routing and WebSocket auth |
| [`background-jobs/celery.md`](background-jobs/celery.md) | Queues, beat schedule, every task |
| [`background-jobs/logging.md`](background-jobs/logging.md) | Logging pipeline, masking, exclusions |
| [`operations/running-the-project.md`](operations/running-the-project.md) | Docker/Make commands, backup/restore, GeoIP update |
| [`operations/testing.md`](operations/testing.md) | pytest setup, current coverage, known gaps |
| [`known-issues.md`](known-issues.md) | Consolidated functional bugs, code smells, drift (English) |
| [`security-considerations.md`](security-considerations.md) | Consolidated security-relevant findings (English) |
| [`future/`](future/) | Predложения и рекомендации по доработке (на русском) |

## Verification performed for this review

The dev stack (`docker-compose.yml`) was actually built and started (`postgres`, `redis`, `django`, `nginx`),
migrations ran cleanly with no errors, and:

- `pytest` was run inside the container: **106 passed, 1 failed** (see
  [Known Issues](known-issues.md#ki-2-note-kind-form-choices-test-failure)).
- `GET /`, `/admin/login/`, `/static/...` all returned 200; `/documents/` redirected to login (302) as expected
  for an anonymous request.
- `GET /health/` returned **500** — investigated and documented (see
  [Known Issues](known-issues.md#ki-3-health-check-returns-500)).
