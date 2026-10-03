# apps.links

A private bookmarks dashboard, independent of the note/document/attachment/comment/sharing cluster — it doesn't
reuse `apps.common`'s `SoftDeleteModel`/`VisibilityModel`, doesn't have comments or sharing, and isn't reachable
from `apps.content`.

## Models (`models.py`)

- **`LinkGroup(OwnedModel, TimeStampedModel)`**: `title`, `cards_per_row` (1–8, default 4), `order` (indexed).
  `Meta.ordering = ["order", "id"]`. Grouping *is* the categorization mechanism — no separate tag/category model.
- **`Link`**: `group` (FK, `CASCADE`), `url` (`URLField`, max 500), `title`, `favicon` (`ImageField`, populated
  server-side, see below), `author` (FK to the user who added it), `order` (indexed).
  **`Link` has no direct `owner` field** — ownership flows transitively through `group.owner`. A future
  `Link.objects.filter(author=request.user)` would be subtly wrong/incomplete (`author` tracks who added it, not
  who owns the containing group) — they're the same person today in single-user mode, but this should be
  revisited before multi-user.

## Favicon fetching (`services.py`, `utils.py`) — SSRF-relevant

`fetch_favicon(url)` is called from `LinkViewSet.perform_create`/`perform_update` whenever a link's URL is
set/changed, and daily by the `refetch_missing_favicons` beat task (below):

1. Parses the user-supplied `url`; only `http`/`https` with a non-empty `netloc` is accepted — anything else
   returns `None` without a request.
2. Tries sources in order, returning the first valid image:
   1. `<scheme>://<netloc>/favicon.ico`;
   2. the link's own page — reads up to `FAVICON_PAGE_MAX_BYTES` (512 KB) of `text/html`, collects
      `<link rel="icon">`/`"shortcut icon"` hrefs (then `apple-touch-icon`) with stdlib `html.parser`, resolves them
      against the final page URL, keeps http(s) only, at most 3 candidates (e.g. gemini.google.com has no
      `/favicon.ico`, only a `<link rel="icon">` to gstatic);
   3. Google's favicon service, `https://www.google.com/s2/favicons?domain=<host>&sz=64` — for sites that block
      server-side requests (Cloudflare bot protection). **Privacy note:** the hostname of any link the first two
      steps fail for is sent to Google. Google answers 404 for an unknown domain, so its placeholder globe is
      rejected by the status check.
3. Every request sends a browser-like `User-Agent` (`FAVICON_HEADERS`) — some sites reject `python-requests/*`.
4. Each image download: `timeout=5s`, streamed in 8 KB chunks, aborted once the running size exceeds
   `FAVICON_MAX_BYTES` (300 KB) — no unbounded memory read even without a `Content-Length` header.
5. Validates `Content-Type: image/*` and `PIL.Image.open(...).verify()` before persisting — rejects an HTML error
   page mislabeled as an image, and a corrupt image (PIL raises `SyntaxError` for a bad PNG checksum).
6. Every failure path (network error, non-200, wrong content-type, oversized, invalid image) is swallowed and
   logged at `INFO`, never raised — a bad/unreachable favicon never blocks saving the link itself.

**Daily retry** (`tasks.py::refetch_missing_favicons`, beat 05:00): runs `services.refetch_missing_favicons()`,
which calls `fetch_favicon` again for every `Link` whose `favicon` is null/empty and saves the ones that succeed
— covers sites that were down or blocking when the link was added. Links with an icon are never touched. In dev
there is no Celery worker; call `apps.links.tasks.refetch_missing_favicons()` from `make docker-shell`.

**No protection against internal/private targets** (loopback, link-local, `169.254.169.254` metadata, RFC1918
ranges) and `requests`' default `allow_redirects=True` is in effect — a redirect to an internal address is
followed transparently. See
[security-considerations.md](../security-considerations.md#sec-5-ssrf-in-link-favicon-fetching) for the full
writeup and recommended fix.

Storage path (`utils.py`): `links/favicons/<owner_id>/<uuid4 hex><ext>` — same randomized-filename convention as
`apps.attachments`.

## API (`api.py`, `serializers.py`)

`LinkGroupViewSet`/`LinkViewSet` — full `ModelViewSet`s plus a custom `reorder` action each. **No
`permission_classes` override** — both rely on the project-wide default `IsAuthenticated`. Both `get_queryset()`s
are correctly scoped (`owner=request.user` / `group__owner=request.user`).
`LinkSerializer.validate_group` double-checks the submitted `group` really belongs to the requesting user at
write time — a solid extra check beyond queryset scoping. `reorder` actions validate the submitted id set is
exactly the caller's own objects before a `bulk_update` — no cross-user reorder possible. `favicon` is
`read_only=True` — clients can only trigger a re-fetch by changing `url`, never set it directly.

## Frontend (`static/links/js/links.js`)

Vanilla JS, no framework/deps. Add/rename/delete group, add/edit/delete link, native HTML5 drag-and-drop
reordering (gated behind a dedicated drag-handle element to avoid conflicting with the card's own click/link
behavior), persisted via the `reorder/` action. All dynamic text goes through a local `esc()` helper before
`innerHTML` interpolation — XSS-safe.
