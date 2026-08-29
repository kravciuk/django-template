"""Maps a short URL slug ("target kind") to the model comments can attach
to, so apps.comments.urls/views resolve `<slug:target_kind>/<uuid:public_id>/`
generically instead of hardcoding Note - and so registering a future
Commentable model is one dict entry (plus, if it needs its own detail page,
one url line) rather than touching this app again.

Only "note" is registered today - it covers both templates/content/
note_detail.html and templates/documents/detail.html (a "document" is the
same Note model, filtered by kind - see apps.documents.views). Registering
apps.attachments.Attachment (which already mixes in CommentableMixin) is
deliberately deferred until it has its own detail page to host a thread on.

Model imports are deferred into each factory function, not module level:
apps.content.models imports apps.comments.mixins at import time, so this
module must stay import-order-safe with respect to apps.content.models.
"""

from collections import namedtuple

TargetKind = namedtuple("TargetKind", ["slug", "get_model", "get_queryset"])


def _note_kind():
    from apps.content.models import Note

    return TargetKind(slug="note", get_model=lambda: Note, get_queryset=lambda: Note.objects.alive())


_REGISTRY_FACTORIES = {
    "note": _note_kind,
}


def get_target_kind(slug):
    """The TargetKind registered under `slug`, or None if it isn't one."""
    factory = _REGISTRY_FACTORIES.get(slug)
    return factory() if factory else None


def target_kind_for(obj):
    """Reverse lookup: the TargetKind whose model matches obj's class, or
    None if obj's model isn't registered under any slug."""
    model = type(obj)
    for factory in _REGISTRY_FACTORIES.values():
        kind = factory()
        if kind.get_model() is model:
            return kind
    return None
