# apps.documents

A UI layer (views/forms/filters/tables/templates) over `apps.content.Note`, restricted to
`kind ∈ {PURCHASE, WARRANTY, CONTRACT}`. **No `models.py`, no migrations — by design**, not an oversight (see
`apps/documents/enums.py`'s in-code comment). This is the "contract / warranty deadline tracking" part of the
project the owner described.

```python
DOCUMENT_KINDS = [NoteKind.PURCHASE, NoteKind.WARRANTY, NoteKind.CONTRACT]  # apps/documents/enums.py
```

Every documents view filters `Note.objects.alive().filter(kind__in=DOCUMENT_KINDS, ...)`. `DocumentForm(NoteForm)`
narrows the base note form's field set/choices and adds `expires_at` back in.

## Where the expiry/warranty date actually lives

`expires_at`/`remind_at` are defined on the shared abstract `ExpiryModel` (`apps.common`), which `Note` inherits
— **not** anything specific to "documents." `Attachment` inherits the same mixin too (so an individual file could
in principle carry its own expiry date), but no UI in either app exposes `Attachment.expires_at`/`remind_at`
today.

**There is no reminder/notification mechanism.** `ExpiryModel`'s own docstring says so explicitly: "No task fires
on these yet — they exist to filter and sort on." Confirmed against the Celery Beat schedule
(`core/celery.py`) — nothing reads `expires_at`/`remind_at` to push a notification. The only place `expires_at`
is used proactively is `HomeView.get_context_data` (`apps.content.views`), which queries "documents expiring in
the next N days" purely to *display* on the home page — a pull-based widget, not a push alert. This is the single
biggest functional gap relative to the stated "warranty deadline tracking" goal — see
[Known Issues](../known-issues.md) and [future/feature-gaps.md](../future/feature-gaps.md).

## Filters / table (`filters.py`, `tables.py`)

`DocumentFilter(django_filters.FilterSet)`, `Meta.model = Note`:

- `status` — `active`/`expired` `ChoiceFilter`; "active" also matches `expires_at__isnull=True` (no expiry counts
  as active).
- `expires_range` — `DateFromToRangeFilter` on `expires_at`.
- `expires_within_days` — `NumberFilter`; casts to `int()` before building a `timedelta()` (its underlying field
  is `Decimal`, which `timedelta()` rejects directly).
- `tags` — comma-separated exact-name match, `.filter(tags__name__in=...).distinct()`.

`DocumentTable(tables.Table)`: columns `title` (links to detail), `kind`, `tags` (per-tag links back into the
filtered list), `expires_at`, computed `status` ("No expiry"/"Expired"/"Active"), `attachments_count`. Default
order: soonest-expiring first (`order_by = ("expires_at",)`). See
[Known Issues](../known-issues.md#ki-6-n1-query-in-documenttable) for an N+1 in the `attachments_count` column.

## Views / URLs (`app_name = "documents"`)

All keyed by `public_id`, consistent with the rest of the project:

| URL | View | Auth |
|---|---|---|
| `list/` (`DocumentListView`) | `LoginRequiredMixin` + `SingleTableMixin` + `FilterView` | scoped `owner=request.user`, `.prefetch_related("tags", "attachments")` |
| `add/` (`DocumentFormView`) | `LoginRequiredMixin` | create |
| `<uuid:public_id>/` (`DocumentDetailView`) | **not** `LoginRequiredMixin` — gated by `can_view()` instead | supports non-owner viewing for PUBLIC/UNLISTED visibility |
| `<uuid:public_id>/edit/` (`DocumentFormView`) | `LoginRequiredMixin`, owner-only via `DocumentOwnershipMixin` | edit |
| `<uuid:public_id>/delete/` (`DocumentDeleteView`) | `LoginRequiredMixin`, owner-only | delete |

`DocumentFormView.post`: on create, `Note.objects.add_root(instance=new_document)` (always a root node — no
nested documents); attachment removal is scoped through the form's pre-filtered `remove_attachments` queryset (so
a user cannot submit another user's attachment PK through this field); new attachments inherit the parent
document's `visibility` **at creation time only** — if the document's visibility later changes, existing
attachments don't follow (see [Known Issues](../known-issues.md)). No explicit pagination override — django-tables2's
default (25/page) applies.

## Templates

`list.html`, `detail.html`, `form.html`, `document_confirm_delete.html`. No htmx usage — plain GET/POST forms plus
the shared `tag_autocomplete.js`. All four correctly use `{% translate %}`/`{% blocktranslate %}` — this app is
i18n-clean; the gap is upstream, in the `NoteForm` base class it inherits from (see
[Known Issues](../known-issues.md#ki-5-missing-i18n-wrapping)).
