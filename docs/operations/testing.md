# Testing

## Setup

Two `pytest.ini` files exist, but only the root one matters at runtime — see
[Known Issues](../known-issues.md#ki-13-duplicate-empty-srcpytestini). `pytest.ini` (project root):

```ini
[pytest]
DJANGO_SETTINGS_MODULE = core.settings.dev
pythonpath = src
python_files = test_*.py *_test.py
testpaths = tests
```

Tests live at the project root under `tests/` (not `src/tests/`), with `pythonpath = src` so `apps.*`/`core.*`
imports resolve. `docker-compose.yml` bind-mounts both `./tests` and `./pytest.ini` into the `django` container
under `/app` specifically so `make docker-test`/a direct `pytest` invocation can find them — without those mounts,
0 tests are collected (see [architecture/docker-topology.md](../architecture/docker-topology.md)).

`tests/conftest.py` provides: `user`/`other_user` fixtures (two real `User` rows), `note_factory` (builds a `Note`
via `add_root`/`add_child`), `tiny_png_bytes` (1×1 PNG bytes for upload tests — note its IDAT checksum is wrong, so `PIL.Image.verify()` rejects it; tests that need a verifiable image generate one with PIL instead, see `test_links_favicons.py`), and an autouse `_media_root`
fixture that redirects `MEDIA_ROOT` to a pytest `tmp_path` — so test file uploads never land in the real
bind-mounted `var/media/`.

## Current state

```
217 passed  (2026-10-03, after adding links favicon fallbacks + daily refetch task)
```

The former KI-2 failure was resolved by updating the test to the deliberate `NoteForm` kind list — see
[Known Issues](../known-issues.md#ki-2-note-kind-form-choices-test-failure-resolved). Treebeard deprecation
warnings may still appear — see [Known Issues](../known-issues.md#ki-4-treebeard-8-deprecation-warnings).

## Coverage by file (`tests/unit/`, `tests/integration/`)

| File | Lines | Covers |
|---|---|---|
| `test_content_views.py` | 370 | `apps.content` views, including `NoteForm` (used by both `content` and `documents`) |
| `test_notifications.py` | 186 | `apps.notifications` model/services/API |
| `test_links.py` | 219 | `apps.links` models/API (`fetch_favicon` mocked) |
| `test_links_favicons.py` | 160 | `apps.links.services.fetch_favicon` source order (`/favicon.ico` → `<link rel="icon">` → Google s2) with `requests.get` faked, non-http schemes, invalid/corrupt images, and the `refetch_missing_favicons` task (no private-IP SSRF tests — none is enforced yet) |
| `test_content_autosave.py` | 142 | Autosave endpoint behavior |
| `test_content.py` | 117 | `apps.content` model/services logic |
| `test_comments_views.py` | 147 | `apps.comments` views/htmx flows |
| `test_attachments.py` | 103 | `apps.attachments` model/validators |
| `test_comments.py` | 79 | `apps.comments` model logic |
| `test_sharing.py` | 72 | `apps.sharing` model/`access.can_view()` logic only — **no test exercises a redemption URL**, consistent with [apps/sharing.md](../apps/sharing.md) (no such view exists) |
| `test_purge_trash.py` (integration) | 71 | `apps.common`'s `purge_trash` command, including `Note`'s tree-safe override |
| `test_tag_suggest.py` | 41 | `apps.content.views.tag_suggest` |
| `test_admin_smoke.py` | 29 | Generic admin-page-loads-without-error smoke test |
| `test_events.py` | — | `apps.events`: hub node, quick-note API, feed (overlap/filters/exclusions), colors, home widget, `NoteForm` calendar fields |
| `test_events_recurrence.py` | — | RRULE build/parse/validate, expansion (DST, all-day, monthly-31st, cap) |
| `test_events_reminders.py` | — | `next_reminder_at`, the save signal, `send_due_reminders` (delivery, recurring advance, stale skip) |
| `test_events_google_mapping.py` | — | Google Calendar mapping: note → event → projection round trip (timed, all-day, end-only, recurrence/UNTIL, reminders, colors, HTML bodies, documents), PATCH bodies, `html_to_text` |
| `test_events_google_sync.py` | — | Sync engine against `google_fake.FakeGoogleCalendar`: insert/import, no echo, partial PATCH, conflicts (later edit wins), rich-text bodies, trash/restore/purge, Google deletions, read-only documents, import window, 410 resync, recurrence round trip, calendar switch, revoked grant, backoff, lock, write cap, save-queued pushes; sync directions (only from / only to Google, switching back to both ways); idle run = 1 Google call + ≤5 queries regardless of note count, `push_pending` flagging (save, purge) and skipping until reconcile, jittered schedule |
| `test_events_google_oauth.py` | — | Connect redirect (state, PKCE, scopes), callback (bad state, partial scopes, success with encrypted tokens), disconnect/revoke, settings page, own OAuth client (stored encrypted, used for connect/exchange/refresh, replacing it drops the connection), site client fallback, undecryptable tokens, no client at all (page opens, connect refused), crypto key rotation, client token refresh / `invalid_grant` |
| `test_events_google_tasks.py` | — | Dispatcher: only due accounts (`next_sync_at`/`next_reconcile_at`), skips backing-off/reconnect/disabled ones, batch cap oldest first, no re-queue while queued, reconcile flag, constance master switch, no push for "only from Google", undecryptable tokens → reconnect |
| `test_events_google_watch.py` | — | Push channels (opened only with the switch + https, kept while fresh, renewed a day before expiry with the old one stopped, moved on calendar switch, stopped when push is off / on disconnect before revoking, forgotten on a revoked grant, refused channel leaves polling) and the webhook (valid change → one debounced interactive sync, handshake, forged token / resource / unknown channel ignored, disabled account, POST only, no CSRF token needed, retry when a sync is running) |
| `test_events_google_ratelimit.py` | — | Shared request budget per OAuth client, budget exhaustion stops requests before Google, project-level vs per-user rate-limit errors, a paused sync postponed without counting as a failure, a push cut short keeps `push_pending` |
| `test_users_timezone.py` | — | Profile time zone validation, `UserTimezoneMiddleware`, form datetimes read in the user's zone |
| `test_users_formats.py` | — | Display formats: language defaults vs profile overrides, template filters, profile form, `<html data-*>` for JS, reminder text |

## Gaps worth knowing before adding tests

- **`apps.documents`** has no dedicated test file — its views/filters/tables are only indirectly exercised
  through `apps.content`'s `NoteForm` tests where the two share code.
- **`apps.users`** has only `test_users_timezone.py` and `test_users_formats.py` (profile time zone/display formats) — the JWT token endpoints (`/api/users/token/`,
  `/api/users/token/refresh/`) and the `user_logged_in` login-metadata signal are untested.
- **`test_purge_trash.py`** is the only file under `tests/integration/` — everything else in that directory is
  currently just `.gitkeep`.
