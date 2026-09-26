# Data model

`apps.common` (`src/apps/common/models.py`) has **no concrete models of its own and no migrations** — it exists
purely to hold abstract base classes that other apps' models compose via multiple inheritance. There is no shared
ancestor beyond `models.Model`; a concrete model must list every trait it wants explicitly.

## Abstract base classes (`apps/common/models.py`)

| Base class | Fields it adds | Notes |
|---|---|---|
| `TimeStampedModel` | `created_at` (auto_now_add, indexed), `updated_at` (auto_now) | |
| `OwnedModel` | `owner` (FK → `AUTH_USER_MODEL`, `CASCADE`, `related_name="%(app_label)s_%(class)s_set"`) | Single owner per object by design — the docstring explicitly rules out a separate ACL system. |
| `PublicIdModel` | `public_id` (UUID4, unique, non-editable) | Non-guessable external identifier so no model reachable outside the admin ever exposes its autoincrement PK. |
| `VisibilityModel(PublicIdModel)` | `visibility` (`Visibility` choices, default `PUBLIC`, indexed) | Extends `PublicIdModel`, so any subclass gets `public_id` too. |
| `SoftDeleteModel` | `deleted_at` (nullable, indexed) | See "Soft delete" below. |
| `ExpiryModel` | `expires_at`, `remind_at` (both nullable, indexed) | For warranty/contract/reminder dates. **No task reads these fields today** — see [Known Issues](../known-issues.md). |

Two enums live in `apps/common/enums.py`:

- `Visibility`: `PUBLIC`, `UNLISTED`, `SHARED`, `PRIVATE`.
- `ContentFormat`: `HTML`, `MARKDOWN`, `PLAIN` — used by `Note.body_format`.

## Soft delete (`apps/common/managers.py`, `apps/common/models.py`)

`SoftDeleteQuerySet` provides `.alive()` (`deleted_at__isnull=True`), `.trashed()`, `.purgeable(cutoff)`
(`trashed().filter(deleted_at__lte=cutoff)`), and bulk `.soft_delete()` / `.restore()`.

**`SoftDeleteManager` deliberately does not filter trashed rows out of `.objects.all()`.** Two reasons, per the
in-code docstring: the admin's "Trashed" list filter needs to see everything, and `apps.content.Note` computes
treebeard's `path`/`numchild` using the plain manager internally — those would desync if soft-deleted rows
vanished from it. **Every other read site must call `.alive()` explicitly.**

`SoftDeleteModel.soft_delete()` / `.restore()` are per-instance; `purge_stale(cls, cutoff, dry_run=False)` is the
default hard-delete implementation, overridable per model — `Note` overrides all three (see
[apps/content.md](../apps/content.md)) because a plain `.delete()` isn't safe for a tree.

The `apps.common.management.commands.purge_trash` command auto-discovers every concrete `SoftDeleteModel`
subclass via `apps.get_models()` and calls `model.purge_stale(cutoff, dry_run=...)` on each — a new app that mixes
in `SoftDeleteModel` gets purge support with zero registration. It is **not** on the Celery Beat schedule (see
[background-jobs/celery.md](../background-jobs/celery.md)) — it's a manually/cron-invoked command today.

See [Known Issues](../known-issues.md#ki-10-bulk-restore-does-not-scope-by-batch) for a gap in the bulk
`.restore()` contract.

## Concrete models and what they compose

| Model | App | Bases (besides `models.Model`) | Notes |
|---|---|---|---|
| `User` | users | `AbstractUser` | Adds `json_data` (schemaless JSONField), `registration_ip`, `last_login_ip`, `registration_date`, `last_login_date`. Does **not** use any `apps.common` base — it's the owner side, not an owned/trashable object. |
| `Note` | content | `MP_Node` (treebeard), `TimeStampedModel`, `OwnedModel`, `VisibilityModel`, `SoftDeleteModel`, `ExpiryModel`, `CommentableMixin`, `ShareableMixin` | The universal content container — see [apps/content.md](../apps/content.md). `Meta.ordering = ["path"]` (required by treebeard). |
| `Attachment` | attachments | `TimeStampedModel`, `OwnedModel`, `VisibilityModel`, `SoftDeleteModel`, `ExpiryModel`, `CommentableMixin`, `ShareableMixin` | Linked to its target via `GenericForeignKey`, not a direct FK — see [apps/attachments.md](../apps/attachments.md). |
| `Comment` | comments | `TimeStampedModel`, `OwnedModel`, `SoftDeleteModel` | Adjacency list (self-FK `parent`), not treebeard — capped at `COMMENTS_MAX_DEPTH` (default 5). |
| `ShareLink` | sharing | `TimeStampedModel`, `OwnedModel` | Token via `secrets.token_urlsafe(32)` (256 bits), optional hashed password, expiry/usage cap. |
| `LinkGroup` / `Link` | links | `OwnedModel` (`LinkGroup` only), `TimeStampedModel` | `Link` has **no direct `owner`** — ownership flows through `group.owner`; see [Known Issues](../known-issues.md). |
| `Notification` | notifications | `TimeStampedModel` | `recipient`/`sender` FKs, optional `GenericForeignKey` target, `payload` JSONField. |

`CommentableMixin` (`apps/comments/mixins.py`) and `ShareableMixin` (`apps/sharing/mixins.py`) are both trivial
abstract mixins that just add a `GenericRelation` (`comments`, `share_links` respectively) — all the actual
comment/sharing logic lives in each app's views/services, not in the mixin.

## `NoteKind` — how one model represents many "kinds" of content

`apps/content/enums.py`:

```
NOTE      — a plain note
ALBUM     — a photo album
PURCHASE  — a purchase record (documents app)
WARRANTY  — a warranty record (documents app)
CONTRACT  — a contract record (documents app)
REMINDER  — defined, but has no supporting UI anywhere yet
NODE      — a hidden "hub" note: Note.save() forces visibility=UNLISTED for this kind regardless of
            what was submitted; its detail page lists its children instead of a body
```

`apps.documents` never has its own model — a "document" is simply `Note.objects.filter(kind__in=[PURCHASE,
WARRANTY, CONTRACT])`. This is a deliberate design choice (see the in-code comment in
`apps/documents/enums.py`), not an oversight, but it means anyone extending "documents" functionality is actually
editing `apps.content.Note`.
