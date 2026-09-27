# apps.content

The core of the whole project: a single polymorphic `Note` model that represents a plain note, a photo album, a
purchase/warranty/contract record, a reminder, or a hidden "hub" node — discriminated by `kind`. `apps.documents`
is just a filtered view over this same model (see [apps/documents.md](documents.md)).

## Model (`models.py`)

`Note(MP_Node, TimeStampedModel, OwnedModel, VisibilityModel, SoftDeleteModel, ExpiryModel, CommentableMixin,
ShareableMixin)`:

| Field | Type | Notes |
|---|---|---|
| `title` | `CharField(max_length=255)` | |
| `kind` | `CharField`, `NoteKind` choices, default `NOTE`, indexed | See [data-model.md](../architecture/data-model.md#notekind--how-one-model-represents-many-kinds-of-content). |
| `body_format` | `CharField`, `ContentFormat` choices, default `HTML` | |
| `body` | `TextField(blank=True)` | Plain text column regardless of format — CKEditor5 is a form widget only, never a storage dependency. |
| `json_data` | `JSONField(default=dict, blank=True)` | Unused anywhere in this app — reserved for future kind-specific structured data. |
| `is_draft` | `BooleanField(default=False, db_index=True)` | Added in migration `0002_note_is_draft.py`. A draft is **owner-only regardless of `visibility`** — enforced in `apps.sharing.access.can_view`. |
| `attachments` | `GenericRelation` → `Attachment` | |
| `tags` | `TaggableManager(blank=True)` | Global namespace, not per-owner — see [Known Issues](../known-issues.md). |

Plus, from its bases: `path`/`depth`/`numchild` (treebeard `MP_Node`, **materialized path**, not nested-set),
`created_at`/`updated_at`, `owner`, `public_id`/`visibility`, `deleted_at`, `expires_at`/`remind_at`, reverse
`comments`/`share_links` relations. `Meta.ordering = ["path"]` — required for treebeard traversal; changing it
would break tree ordering.

**`NoteKind.NODE` special case**: `Note.save()` forces `visibility = UNLISTED` whenever `kind == NODE`,
unconditionally, regardless of what the form/admin/shell requested — "so it can never end up PUBLIC and listed."
A Node's detail page lists its children instead of rendering a body.

**HTML sanitization**: whenever `body_format == HTML`, `Note.save()` runs `body` through
`libs/html.py::sanitize_html()` (an `nh3`/ammonia allowlist — `script`/`style`/`iframe`/`on*` attributes are never
allowlisted) before persisting. Templates render `{{ object.body|safe }}` — safe specifically because sanitization
already happened at save time, for every entry point (admin, public form, future API).

## Managers (`managers.py`)

```python
class NoteQuerySet(MP_NodeQuerySet, SoftDeleteQuerySet): pass
class NoteManager(MP_NodeManager.from_queryset(NoteQuerySet)):
    def get_queryset(self):
        return self._queryset_class(self.model, using=self._db).order_by("path")
```

The `get_queryset()` override exists because treebeard's own `MP_NodeManager.get_queryset()` hardcodes
`MP_NodeQuerySet(...)` instead of respecting `self._queryset_class` — a naive `.from_queryset()` composition
would silently produce a manager whose `.alive()`/`.trashed()` proxy methods return a plain `MP_NodeQuerySet`
that doesn't have them. This override fixes that and preserves the mandatory `.order_by("path")`.

Soft delete on `Note` is **not** the base class's default — `Note` overrides `soft_delete()`, `restore()`, and
`purge_stale()` to delegate to `services.py` (below), because a tree needs cascading, same-timestamped
soft-delete/restore and subtree-safe hard-delete.

## Tree usage (treebeard `MP_Node`)

Building the tree only happens in `views.py::_persist_note`: `Note.objects.add_root(instance=...)` for a
top-level note, `Note.objects.add_child(parent, instance=...)` for a nested one. **No `move()` calls anywhere in
this app** — re-parenting an *existing* note isn't supported by the public `NoteForm` (the `parent` field is
deleted from the form entirely when editing). The **admin** form (`admin.py`, `movenodeform_factory`) does
support moves — re-parenting is admin-only today.

`note.get_ancestors()`/`note.get_children()` (instance methods) are used for breadcrumbs/child listings —
**deprecated by treebeard 8** in favor of `Note.objects.get_ancestors(note)`/`get_children(note)`; pytest surfaces
`RemovedInTreebeard8Warning` for both call sites (see [Known Issues](../known-issues.md#ki-4-treebeard-8-deprecation-warnings)).

## Views / URLs (`views.py`, `urls.py`, `app_name = "content"`)

| URL | Name | View | Auth |
|---|---|---|---|
| `` | `home` | `HomeView` (ListView) | anonymous OK, but renders an empty dashboard for anonymous visitors — see below |
| `add/` | `note_add` | `NoteFormView` | login required |
| `add/autosave/` | `note_autosave_add` | `NoteAutosaveView` | login required |
| `drafts/` | `note_drafts` | `DraftListView` | login required |
| `tags/suggest/` | `tag_suggest` | FBV, `@login_required` | login required |
| `<uuid:public_id>/` | `note_detail` | `NoteDetailView` | gated by `can_view()`, not `LoginRequiredMixin` |
| `<uuid:public_id>/edit/` | `note_edit` | `NoteFormView` | login required, owner-only |
| `<uuid:public_id>/autosave/` | `note_autosave_edit` | `NoteAutosaveView` | login required, owner-only |

- `HomeView.get_queryset`: for anonymous visitors, returns `[]` outright — no query, no notes dashboard (see
  "Anonymous vs. authenticated home page" below). For logged-in users:
  `Note.objects.alive().filter(visibility=PUBLIC, is_draft=False).order_by("-created_at")[:10]` — a **hard slice,
  no `Paginator`** — there is no pagination on the home feed. It also issues one extra query *per note* to find
  each note's cover image (no `prefetch_related`) — see
  [Known Issues](../known-issues.md#ki-7-n1-query-on-home-page-cover-images). It also adds
  `recent_documents`/`expiring_documents` (scoped `owner=request.user`, deliberately excluded for anonymous
  visitors — "not someone else's warranties").
- `NoteDetailView.get`: 404s (not 403) when `can_view()` denies access — deliberately indistinguishable from "does
  not exist." For a `NODE`-kind note, lists children with a Python-side `can_view()` re-check per child (no
  pagination there either).
- `NoteOwnershipMixin.get_object`: the only ownership gate on create/edit — 403 if the note exists but belongs to
  someone else, 404 if it doesn't exist/is trashed.
- `NoteFormView.post` always sets `is_draft = False` on submit — any explicit save (new or resuming a draft)
  finalizes it. Handles attachment removal (soft-deletes the selected `Attachment`s) and new uploads.
- `NoteFormView.get` has "auto-resume" logic: opening `?parent=<public_id>` looks for an existing unfinished
  draft under that same parent first, redirecting to it instead of starting a blank form — a mitigation for the
  autosave-duplicate race (see [Known Issues](../known-issues.md#ki-8-autosave-race-can-create-duplicate-notes)),
  but only across separate visits, not within one in-flight page.
- `NoteAutosaveView.post`: relaxes `title`/`body` to optional; sets `is_draft=True` only on create, leaves it
  untouched on every subsequent autosave of an existing note.
- `tag_suggest`: searches `Tag.objects.filter(name__icontains=query)` **globally across every user's notes** —
  explicitly flagged in-code as a single-user-only tradeoff, see
  [security-considerations.md](../security-considerations.md).

## Forms (`forms.py`)

`NoteForm` — public create/edit form. `kind` choices are narrowed at the form level
(`FORM_NOTE_KIND_CHOICES = [NOTE, ALBUM, NODE]`) — the model itself stays fully general (purchase/warranty/
contract/reminder exist as `NoteKind` values with no supporting UI here; they're created/edited through
`apps.documents` instead). See [Known Issues](../known-issues.md#ki-2-note-kind-form-choices-test-failure) for a
test that currently fails against this exact choice list.

`attachments` (multi-file upload) and `remove_attachments` (checkbox list, scoped to
`self.instance.attachments.alive()`) are plain form fields, not model fields — `Attachment` is linked via
`GenericRelation`, so the view handles both explicitly after `save()`. Widget for `body` swaps between
CKEditor5 and a monospace `Textarea` based on `body_format` — takes effect on reload, not live in the browser
(same caveat duplicated in the admin's `NoteBaseForm`).

## `services.py` — cascading tree-safe soft delete

- `soft_delete_note(note)` — trashes the note **and** its full subtree (`get_descendants(include_self=True)`)
  **and** every `Attachment`/`Comment` hanging off any of those, all stamped with one shared `timezone.now()`.
- `restore_note(note)` — only rows stamped with that exact `deleted_at` value come back, so a descendant trashed
  separately/earlier isn't accidentally restored.
- `purge_stale_notes(cutoff, dry_run)` — treebeard's `MP_NodeQuerySet.delete()` always expands a non-leaf match
  to its full subtree **by path prefix, regardless of trash status**, so a naive
  `Note.objects.purgeable(cutoff).delete()` could hard-delete live descendants of an old trashed ancestor. This
  walks trashed-and-stale candidates by depth and only hands a subtree to `.delete()` once every one of its
  descendants is independently confirmed trashed-and-stale too; otherwise it skips and logs a warning.
- `soft_delete_stale_drafts(cutoff)` — iterates `Note.objects.alive().filter(is_draft=True,
  updated_at__lte=cutoff)` row by row, calling `soft_delete_note()` on each (used by `tasks.py`, below).

## `tasks.py` — `cleanup_stale_drafts`

Celery task `apps.content.tasks.cleanup_stale_drafts` (on the Beat schedule, daily 02:00 — see
[background-jobs/celery.md](../background-jobs/celery.md)): cutoff = `now() - DRAFT_RETENTION_DAYS` (default 7),
then `soft_delete_stale_drafts(cutoff)`. This only **trashes** stale drafts — they still sit in the trash for the
separate `TRASH_RETENTION_DAYS` window (default 30) before `purge_trash` hard-deletes them.

## `text.py` — `excerpt()`

Produces a ≤20-word preview of `Note.body` for the home feed. HTML bodies: a small `HTMLParser` subclass returns
the text of the first top-level `<div>`/`<p>` (falls back to `strip_tags()` otherwise). Markdown/plain bodies:
text up to the first blank line. Used only by `HomeView`.

## Frontend JS (`static/content/js/`)

- **`note_autosave.js`** — debounces on `input`/`change` (2s) **plus an unconditional 15s poll**, because
  CKEditor5 syncs into the underlying `<textarea>` programmatically without firing native DOM events (the
  debounce path alone would never fire for rich-text edits). Skips file inputs entirely. Uses
  `navigator.sendBeacon` as a last-gasp save on `pagehide`/tab-hide — this beacon path bypasses the in-memory
  `saving` guard that the normal fetch path uses, which is one of two concrete causes of the duplicate-note race
  documented in [Known Issues](../known-issues.md#ki-8-autosave-race-can-create-duplicate-notes).
- **`tag_autocomplete.js`** — progressive-enhancement chip UI over the taggit-rendered tag input; debounced (200ms)
  fetch against `content:tag_suggest` (global across users, see above).
- **`weather-widget.js`** — a self-contained, dependency-free widget calling the free, keyless
  `api.open-meteo.com` API directly from the browser. **Hardcoded to Vilnius, Lithuania** coordinates; `home.html`
  never passes per-user coordinates, so every visitor sees the same fixed-location forecast forever. Not
  connected to `GEOIP_PATH`/GeoIP2 in any way — see [Known Issues](../known-issues.md#ki-11-weather-widget-is-a-hardcoded-vilnius-forecast).

## Anonymous vs. authenticated home page

The project is currently single-user (see the top-level `CLAUDE.md`), so the root URL (`content:home`, served by
`HomeView`/`home.html`) is intentionally split by `user.is_authenticated`, both in the shared header
(`templates/base.html`) and in the page content:

- **Header (`templates/base.html`, the left-hand nav item group, not blockified — inline in the single shared
  template used by every page)**: authenticated users see the "Notes" / "Documents" / "Links" links (to
  `content:home` / `documents:list` / `links:home`); anonymous visitors see "About project" / "FAQ" instead. Both
  are currently **placeholder `href="#"` links** — no `about`/`faq` views, URLs, or templates exist anywhere in the
  project yet; wire them up to real pages once that content exists. The right-hand nav group (add note/add
  document/drafts/username/notifications vs. a "Log in" link) was already conditional on `user.is_authenticated`
  before this and is unrelated to this split.
- **Home page content (`content/home.html`)**: the entire `{% block content %}` (recent-notes masonry, recent/
  expiring documents, the weather widget) plus `{% block extra_head %}` (the weather widget's CSS/JS) and the
  default `{% block breadcrumbs %}` are now wrapped in `{% if user.is_authenticated %}` — an anonymous visitor gets
  a valid 200 response with an empty page (title and header only, no breadcrumb). `HomeView.get_queryset` mirrors
  this by returning `[]` immediately for anonymous requests instead of querying public notes.

Before this change, both groups saw the same dashboard (including a teaser of `Visibility.PUBLIC` notes) — that
public-facing teaser is gone for now; if it needs to come back (e.g. as part of the "About project" page), restore
the `visibility=PUBLIC` query in `HomeView.get_queryset` rather than lifting the whole `is_authenticated` gate.

## Templates

`home.html`, `note_form.html`, `note_detail.html`, `note_drafts.html` plus two shared includes:
`includes/_form_fields.html` (generic Bootstrap field renderer) and `includes/_object_body.html` (shared between
`note_detail.html` and `documents/detail.html` — both render the same underlying `Note`). `_object_body.html` is
the only one of these that actually uses `{% load i18n %}`/`{% translate %}` — see
[Known Issues](../known-issues.md#ki-5-missing-i18n-wrapping) for the rest.
