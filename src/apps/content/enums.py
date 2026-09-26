from django.db import models
from django.utils.translation import gettext_lazy as _


class NoteKind(models.TextChoices):
    NOTE = "note", _("Note")
    ALBUM = "album", _("Album")
    PURCHASE = "purchase", _("Purchase")
    WARRANTY = "warranty", _("Warranty")
    CONTRACT = "contract", _("Contract")
    REMINDER = "reminder", _("Reminder")
    # A hidden hub note: never listed, always reachable only via its own
    # direct link (Note.save() forces visibility=UNLISTED for this kind),
    # and its detail page lists its child notes instead of a body - see
    # apps/content/views.py::NoteDetailView.
    NODE = "node", _("Node")
