from django.utils.translation import gettext_lazy as _

from apps.content.enums import NoteKind

# A "document" is just an apps.content.Note whose kind is one of these -
# the model itself stays fully general (Note.kind also has NOTE/ALBUM/
# REMINDER, used by apps.content), this app only ever creates/lists/edits
# notes restricted to this subset.
DOCUMENT_KINDS = [NoteKind.PURCHASE, NoteKind.WARRANTY, NoteKind.CONTRACT]

DOCUMENT_KIND_CHOICES = [
    (NoteKind.CONTRACT, _("Contract")),
    (NoteKind.PURCHASE, _("Purchase / receipt")),
    (NoteKind.WARRANTY, _("Warranty")),
]
