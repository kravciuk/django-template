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
via `add_root`/`add_child`), `tiny_png_bytes` (a valid 1×1 PNG for upload tests), and an autouse `_media_root`
fixture that redirects `MEDIA_ROOT` to a pytest `tmp_path` — so test file uploads never land in the real
bind-mounted `var/media/`.

## Current state (as run for this review)

```
106 passed, 1 failed, 8 warnings in 18.42s
```

The one failure is a real, currently-broken assertion, not a flaky test — see
[Known Issues](../known-issues.md#ki-2-note-kind-form-choices-test-failure). The 8 warnings are all the same
`RemovedInTreebeard8Warning` surfacing from two call sites — see
[Known Issues](../known-issues.md#ki-4-treebeard-8-deprecation-warnings).

## Coverage by file (`tests/unit/`, `tests/integration/`)

| File | Lines | Covers |
|---|---|---|
| `test_content_views.py` | 370 | `apps.content` views, including `NoteForm` (used by both `content` and `documents`) |
| `test_notifications.py` | 186 | `apps.notifications` model/services/API |
| `test_links.py` | 219 | `apps.links` models/API (does not appear to specifically exercise the SSRF-relevant paths in `services.py::fetch_favicon` against a hostile URL) |
| `test_content_autosave.py` | 142 | Autosave endpoint behavior |
| `test_content.py` | 117 | `apps.content` model/services logic |
| `test_comments_views.py` | 147 | `apps.comments` views/htmx flows |
| `test_attachments.py` | 103 | `apps.attachments` model/validators |
| `test_comments.py` | 79 | `apps.comments` model logic |
| `test_sharing.py` | 72 | `apps.sharing` model/`access.can_view()` logic only — **no test exercises a redemption URL**, consistent with [apps/sharing.md](../apps/sharing.md) (no such view exists) |
| `test_purge_trash.py` (integration) | 71 | `apps.common`'s `purge_trash` command, including `Note`'s tree-safe override |
| `test_tag_suggest.py` | 41 | `apps.content.views.tag_suggest` |
| `test_admin_smoke.py` | 29 | Generic admin-page-loads-without-error smoke test |

## Gaps worth knowing before adding tests

- **`apps.documents`** has no dedicated test file — its views/filters/tables are only indirectly exercised
  through `apps.content`'s `NoteForm` tests where the two share code.
- **`apps.users`** has no test file — the JWT token endpoints (`/api/users/token/`,
  `/api/users/token/refresh/`) and the `user_logged_in` login-metadata signal are untested.
- **`test_purge_trash.py`** is the only file under `tests/integration/` — everything else in that directory is
  currently just `.gitkeep`.
