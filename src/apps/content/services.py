import logging

from django.utils import timezone

from apps.attachments.models import Attachment
from apps.comments.models import Comment

from .models import Note

logger = logging.getLogger("apps")


def _content_type_filter():
    """Attachment/Comment target Note via a generic FK - filtering by
    app_label/model instead of importing ContentType.objects.get_for_model
    avoids a query and stays correct across app relabeling.
    """
    return {"content_type__app_label": "content", "content_type__model": "note"}


def soft_delete_note(note):
    """Cascade-trash a note: itself, its whole subtree, and every
    attachment/comment hanging off any of those - all stamped with the SAME
    timestamp. That shared stamp is what makes restore_note() exact without
    needing real versioning (see restore_note).
    """
    stamp = timezone.now()
    subtree_ids = list(
        Note.objects.get_descendants(note, include_self=True)
        .filter(deleted_at__isnull=True)
        .values_list("pk", flat=True)
    )
    if not subtree_ids:
        return stamp

    Note.objects.filter(pk__in=subtree_ids).update(deleted_at=stamp)
    Attachment.objects.filter(
        object_id__in=subtree_ids, deleted_at__isnull=True, **_content_type_filter(),
    ).update(deleted_at=stamp)
    Comment.objects.filter(
        object_id__in=subtree_ids, deleted_at__isnull=True, **_content_type_filter(),
    ).update(deleted_at=stamp)
    note.deleted_at = stamp
    return stamp


def restore_note(note):
    """Undo exactly one soft_delete_note() call: only rows stamped with
    this note's own deleted_at come back, so a descendant trashed earlier
    and separately isn't swept back in by accident.
    """
    if note.deleted_at is None:
        return
    stamp = note.deleted_at
    subtree_ids = list(
        Note.objects.get_descendants(note, include_self=True)
        .filter(deleted_at=stamp)
        .values_list("pk", flat=True)
    )
    Note.objects.filter(pk__in=subtree_ids).update(deleted_at=None)
    Attachment.objects.filter(object_id__in=subtree_ids, deleted_at=stamp, **_content_type_filter()).update(
        deleted_at=None,
    )
    Comment.objects.filter(object_id__in=subtree_ids, deleted_at=stamp, **_content_type_filter()).update(
        deleted_at=None,
    )
    note.deleted_at = None


def purge_stale_notes(cutoff, dry_run=False):
    """Hard-delete only whole Note subtrees where every node is already
    trashed and past `cutoff`.

    treebeard's queryset delete() (MP_NodeQuerySet.delete, what actually
    runs the row deletion) always expands a non-leaf match to its FULL
    subtree by path prefix - regardless of trash status. A naive
    `Note.objects.purgeable(cutoff).delete()` could therefore hard-delete
    live (or not-yet-stale) descendants of an old trashed ancestor. So this
    only ever hands `.delete()` a queryset already verified to be exactly
    the closed, fully-stale subtree.
    """
    candidates = Note.objects.trashed().filter(deleted_at__lte=cutoff).order_by("depth")
    purged = 0
    skipped = 0
    seen_pks = set()

    for note in candidates.iterator():
        if note.pk in seen_pks:
            continue  # already handled as part of an ancestor's subtree this run

        descendants = Note.objects.get_descendants(note, include_self=True)
        if descendants.exclude(deleted_at__lte=cutoff).exists():
            skipped += 1
            continue

        pks = list(descendants.values_list("pk", flat=True))
        seen_pks.update(pks)

        if dry_run:
            purged += len(pks)
        else:
            count, _ = descendants.delete()
            purged += count

    if skipped:
        logger.warning(
            "purge_trash: skipped %d Note subtree(s) with live or not-yet-stale descendants", skipped,
        )
    return purged
