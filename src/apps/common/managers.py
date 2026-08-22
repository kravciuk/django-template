from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    """Queryset for soft-deletable models.

    Provides no default filtering - see SoftDeleteManager's docstring for
    why. Callers must call `.alive()` or `.trashed()` explicitly wherever
    "not in the trash" is the intended meaning.
    """

    def alive(self):
        return self.filter(deleted_at__isnull=True)

    def trashed(self):
        return self.filter(deleted_at__isnull=False)

    def purgeable(self, cutoff):
        """Trashed rows whose deleted_at is at or before `cutoff`."""
        return self.trashed().filter(deleted_at__lte=cutoff)

    def soft_delete(self):
        """Bulk soft-delete: every row gets the SAME timestamp, so a later
        `.restore()` on the resulting deleted_at value can undo exactly this
        batch and nothing trashed earlier or separately."""
        return self.filter(deleted_at__isnull=True).update(deleted_at=timezone.now())

    def restore(self):
        return self.update(deleted_at=None)


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    """Manager for soft-deletable models.

    Deliberately does NOT filter out trashed rows by default - `.objects.all()`
    still returns everything. Two reasons this matters:

    - Admin list views need to see trashed rows for the "Trashed" filter
      (see apps.common.admin.TrashedFilter) and for the recycle-bin UI.
    - apps.content.Note computes its treebeard `path`/`numchild` using
      `objects` internally; if that queryset silently excluded soft-deleted
      rows, tree arithmetic (child counts, path holes) would desync from
      what's actually in the table.

    Call `.alive()` / `.trashed()` explicitly wherever "not deleted" is the
    intended semantics.
    """


