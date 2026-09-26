# apps.comments

A generic, reusable threaded-comment component. Any model that mixes in `CommentableMixin`
(`apps/comments/mixins.py` — just adds a `comments` `GenericRelation`) can have comments; a small registry maps a
URL-safe "target kind" slug to the actual model/queryset, so comment URLs/views never hardcode a specific model.

## Model (`models.py`)

`Comment(TimeStampedModel, OwnedModel, SoftDeleteModel)`:

- `content_type`/`object_id`/`target` — `GenericForeignKey`.
- `parent` — self-FK (`related_name="replies"`) — **adjacency list**, not treebeard/MPTT. The model's own
  docstring explains why: comments are capped at depth 5 (`COMMENTS_MAX_DEPTH`), so a denormalized path isn't
  worth it the way it is for `Note`'s genuinely unbounded tree.
- `depth` — recomputed in `save()` as `parent.depth + 1` (or `1` for a root comment). **Enforced twice**:
  dynamically in `Comment.clean()` (reads the live `COMMENTS_MAX_DEPTH` setting) *and* by a hardcoded DB
  `CheckConstraint` (`depth BETWEEN 1 AND 5`) — the model's own docstring flags the mismatch risk if the setting
  is ever raised above 5 without a matching migration (validation would pass, the DB would still reject with a
  raw `IntegrityError`).
- `body`, `ip` (captured server-side by the view), `edited_at` (auto-stamped when `body` changes, via an
  `_original_body` snapshot captured in `from_db()`).

Soft delete has **no cascade to replies** — `CommentDeleteView` trashes only the target comment; if it still has
alive replies, the template renders it as a `[deleted]` placeholder instead of orphaning the subtree.

## Registry (`registry.py`)

```python
_REGISTRY_FACTORIES = {"note": _note_kind}   # get_target_kind("note") -> (Note, Note.objects.alive())
```

**Only `"note"` is registered today** (covers both `content/note_detail.html` and `documents/detail.html`, since
"document" is just `Note` filtered by kind). `apps.attachments.Attachment` already mixes in `CommentableMixin` —
it has a `comments` relation — but is **deliberately not registered yet** (no reachable comment URLs/UI for
attachments until they get their own detail page). Model imports are deferred inside each factory function to
avoid a circular import with `apps.content.models`.

## Rendering / sanitization (`templatetags/comment_markdown.py`)

`render_comment_body`: `markdown.markdown(value, extensions=["fenced_code", "nl2br"])`, then the **same**
`libs/html.py::sanitize_html()` allowlist used for `Note.body`, then `mark_safe()`. Raw HTML/`<script>` embedded
in a comment's markdown source is stripped exactly like a `Note` body would be — no weaker/separate sanitization
path, no stored-XSS route found.

## Views (`views.py`) — permission model

**Any authenticated user who can view the target can comment on it** — every view (`CommentThreadView`,
`CommentCreateView`, `CommentReplyView`) gates on `can_view(target, request.user)`, not "owner/collaborators
only." Since `can_view()` allows `PUBLIC`-visibility objects for any authenticated user, this means (once
multi-user) any logged-in user can comment on any other user's public note — this reads as an intentional
blog-style design choice, not an oversight, but is worth confirming before multi-user launch.

Create/reply views are htmx-only, POST-only; an unauthenticated POST gets a plain `PermissionDenied` (403) rather
than `LoginRequiredMixin`'s redirect, specifically so htmx doesn't swap the login page's HTML into the comment
thread. Max-depth is enforced server-side via `Comment.clean()` inside `full_clean()` — independent of the
template's `{% if comment.depth < max_depth %}` Reply-button gating, so there's no client-side bypass. Edit/delete
are restricted to the comment's own owner, and re-check `can_view()` on the target too (losing view access to the
target — e.g. it going private — also blocks editing your own old comment on it).

## `services.py`

`thread_context(request, target, *, page=None, form=None)` — the single shared context-builder used by the
inline `{% include %}` on note/document detail pages, the paginated `CommentThreadView`, and create/reply views'
re-render. Deliberately queries `target.comments.filter(parent__isnull=True)` **without** `.alive()` — a trashed
parent with alive replies must stay queryable so the recursive template walk doesn't orphan the reply subtree.
Paginates top-level comments only, 20/page.

## Known issues

Hardcoded (non-`gettext`) strings in `models.py`'s two `ValidationError`s and `admin.py`'s one field label — see
[Known Issues](../known-issues.md#ki-5-missing-i18n-wrapping). The `COMMENTS_MAX_DEPTH`/DB-constraint mismatch
risk above is also tracked there.
