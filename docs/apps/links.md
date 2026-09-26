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
set/changed:

1. Parses the user-supplied `url`; bails only if `scheme`/`netloc` are empty — **no allow-list restricting to
   `http`/`https`**.
2. Always requests `<scheme>://<netloc>/favicon.ico` — the request's own host, not an arbitrary attacker path.
3. `timeout=5s`, streamed in 8 KB chunks, aborted once the running size exceeds `FAVICON_MAX_BYTES` (300 KB) — no
   unbounded memory read even without a `Content-Length` header.
4. Validates `Content-Type: image/*` and `PIL.Image.open(...).verify()` before persisting — rejects an HTML error
   page mislabeled as an image.
5. Every failure path (network error, non-200, wrong content-type, oversized, invalid image) is swallowed and
   logged at `INFO`, never raised — a bad/unreachable favicon never blocks saving the link itself.

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
