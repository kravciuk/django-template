from treebeard.mp_tree import MP_NodeManager, MP_NodeQuerySet

from apps.common.managers import SoftDeleteQuerySet


class NoteQuerySet(MP_NodeQuerySet, SoftDeleteQuerySet):
    pass


class NoteManager(MP_NodeManager.from_queryset(NoteQuerySet)):
    """MP_NodeManager.get_queryset() hardcodes `MP_NodeQuerySet(...)` rather
    than using `self._queryset_class`, so `.from_queryset(NoteQuerySet)`
    alone would copy .alive()/.trashed()/.purgeable() onto this manager as
    proxies that call self.get_queryset() - and get back a plain
    MP_NodeQuerySet without those methods. Overriding get_queryset() here
    (mirroring MP_NodeManager's own implementation, but with NoteQuerySet)
    is required for the soft-delete methods to actually work, and also
    preserves the `.order_by("path")` treebeard relies on for tree
    traversal.
    """

    def get_queryset(self):
        return self._queryset_class(self.model, using=self._db).order_by("path")
