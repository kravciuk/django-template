# REST endpoints

Global DRF configuration (`core/settings/base.py`): `SessionAuthentication` + DRF `TokenAuthentication` +
`rest_framework_simplejwt.JWTAuthentication` stacked, `IsAuthenticated` default permission,
`PageNumberPagination` (`PAGE_SIZE=50`). Unless noted, every endpoint below relies on these defaults with no
per-view override.

| Prefix | App | Endpoints | Auth notes |
|---|---|---|---|
| `/api/users/` | users | `token/` (`TokenObtainPairView`), `token/refresh/` (`TokenRefreshView`) | Stock SimpleJWT views, no customization. Authenticates directly against username+password - bypasses django-allauth's rate limiting and 2FA entirely, see [security-considerations.md](../security-considerations.md). |
| `/accounts/...` | users (django-allauth) | login/logout/signup/password reset/email management/2FA | Not a REST API - server-rendered, session-based. See [apps/users.md](../apps/users.md#authentication-django-allauth). |
| `/accounts/profile/` | users | `ProfileUpdateView` (first/last name, time zone) | `LoginRequiredMixin`, session auth only. |
| `/api/notifications/` | notifications | `NotificationViewSet` (list/retrieve/delete + `mark_read`, `mark_all_read`, `unread_count`) | Scoped to `recipient=request.user`; read-only serializer (creation only via `services.notify()`). |
| `/events/api/feed/`, `/events/api/tags/`, `/events/api/notes/` | events | `CalendarFeedView` (GET), `CalendarTagsView` (GET), `QuickNoteViewSet` (create/retrieve/partial_update/destroy by `public_id`) | Scoped to `owner=request.user`; documents and hub nodes 404 on the notes endpoint; DELETE soft-deletes. Language-prefixed (under `i18n_patterns`), like links. See [apps/events.md](../apps/events.md#urls-app_name--events-under-i18n_patterns). |
| `/links/api/groups/`, `/links/api/links/` | links | Full `ModelViewSet`s + `reorder` action each | Scoped to `owner=request.user` / `group__owner=request.user`; extra ownership check on the `group` FK at write time. |

There is no project-wide `/api/` router — each app that exposes a REST API mounts its own router under its own
URL prefix (`core/urls.py`).

## Non-REST, server-rendered views

Most of the app (`content`, `documents`, `attachments`, `comments`, `sharing`) is plain Django views (CBVs) +
server-rendered templates, some enhanced with htmx (comments) or vanilla JS + `fetch()` (autosave, tag
autocomplete, links reorder, notifications bell) — not DRF. See each app's page under [`apps/`](../apps/) for its
URL table.

## Access control that isn't DRF permission classes

Several object-detail views (`NoteDetailView`, `DocumentDetailView`, attachment download) are intentionally
**not** gated by `LoginRequiredMixin` — they call `apps.sharing.access.can_view(obj, request.user)` instead, so
that `PUBLIC`/`UNLISTED`-visibility objects remain reachable by anonymous visitors. See
[architecture/data-model.md](../architecture/data-model.md) and [apps/sharing.md](../apps/sharing.md).
