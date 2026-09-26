# apps.attachments

A generic, reusable file-attachment subsystem. Owns the `Attachment` model, upload validation, HEIC→JPEG
conversion, thumbnailing (imagekit), and file-cleanup-on-delete. Attached to whatever it's attached to via
`GenericForeignKey`, not a direct FK — deliberately, to avoid a circular `Note.attachments` ↔ `Attachment.note`
package dependency and to let other future models reuse it without editing this app.

## Model (`models.py`)

`Attachment(TimeStampedModel, OwnedModel, VisibilityModel, SoftDeleteModel, ExpiryModel, CommentableMixin,
ShareableMixin)`:

| Field | Notes |
|---|---|
| `content_type`/`object_id`/`target` | `GenericForeignKey` — the "owning" object. |
| `position`, `is_cover` | `is_cover` has a `UniqueConstraint(condition=Q(is_cover=True))` — at most one cover per target. |
| `file` | `FileField`, validated by `validate_upload_size`/`validate_upload_extension`. |
| `kind` | `AttachmentKind` enum (`IMAGE`/`DOCUMENT`/`AUDIO`/`VIDEO`/`OTHER`) — auto-classified from the filename's guessed MIME type, **not** file content (see Security below). |
| `original_name`, `mime_type`, `size`, `checksum` (sha256, streamed), `width`/`height` (images) | Metadata, re-extracted on every save where the `file` field itself changed. |
| `title`, `description`, `tags` | |

**Storage path**: `attachments/{owner_id}/{YYYY}/{MM}/{uuid4().hex}{ext}` (`utils.py`) — fully randomized, original
filename preserved only in `original_name`. Deliberately prevents path traversal, filename collisions, and
guessing another attachment's URL from a predictable path.

**HEIC/HEIF handling**: converted to JPEG **in memory before storage** (not just for the thumbnail) — depends on
`pillow_heif.register_heif_opener()` running in `AttachmentsConfig.ready()`.

## Validation (`validators.py`) — security-relevant

```python
DEFAULT_ALLOWED_EXTENSIONS = []  # empty = no restriction
```

`validate_upload_extension` checks only the filename's extension (lower-cased, both sides) against
`ATTACHMENTS_ALLOWED_EXTENSIONS`. **No magic-byte/content sniffing anywhere.** `mime_type` is also
filename-derived (`mimetypes.guess_type`), used only for display/classification, never for validation. With the
default empty whitelist, **any file type can be uploaded**, subject only to the size cap. See
[security-considerations.md](../security-considerations.md#sec-4-no-contentmagic-byte-validation-on-uploads).

No double-extension or case-sensitivity bypass was found in the whitelist check itself, and no null-byte/path
traversal risk exists since the stored filename is always a fresh `uuid4().hex`, never derived from user input.

## Signals (`signals.py`)

```python
@receiver(post_delete, sender=Attachment)
def delete_file_from_disk(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)
```

Fires on **hard delete only** (via `purge_trash`, admin's "permanently delete," or DB cascade) — soft delete
(`.soft_delete()`, just sets `deleted_at`) never touches the file, correctly, since it must survive until purge.
No logging/retry around a storage-backend failure here — see [Known Issues](../known-issues.md).

## Thumbnails (`templatetags/attachment_images.py`)

`safe_thumbnail(source, width, height, css_class)` — force-generates an imagekit cache file **synchronously at
template-render time**, wrapped in a bare `try/except Exception` (logs a warning, returns `""` on failure — a
single corrupt upload can't crash a whole page). No pre-generation on upload, no async task — the first render of
any given size pays the full Pillow decode/JPEG-encode cost inline; subsequent renders hit imagekit's cache.

## Views / Admin

`attachments/views.py` serves downloads gated by `can_view()` from `apps.sharing.access` — per-owner/visibility
permission is correctly enforced today (an attachment has its own `owner`/`visibility`, independent of its
target's). `admin.py` registers `Attachment` with `SoftDeleteAdminMixin` + a `TrashedFilter`, and provides
`AttachmentInline` (a `GenericTabularInline`, reused by `NoteAdmin`) with an inline image preview for
image-kind attachments.

## Known issues / edge cases

See the consolidated lists for full detail:
- [Known Issues](../known-issues.md) — orphaned-file risk on hard-delete failure, unbounded synchronous thumbnail
  cost, an attachment's visibility not following its parent document's visibility if that changes later.
- [Security Considerations](../security-considerations.md#sec-4-no-contentmagic-byte-validation-on-uploads) —
  extension-only upload validation.
