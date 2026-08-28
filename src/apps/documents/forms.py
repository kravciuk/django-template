from django import forms
from django.utils.translation import gettext_lazy as _

from apps.common.enums import Visibility
from apps.content.forms import NoteForm
from apps.content.models import Note

from .enums import DOCUMENT_KIND_CHOICES


class DocumentForm(NoteForm):
    """Create/edit form for a "document" (contract/receipt/warranty).

    Reuses apps.content.NoteForm wholesale (same title/tags/body/visibility
    fields, same multi-file attachments/remove_attachments handling) but:
    - restricts `kind` to the document kinds instead of note/album;
    - adds `expires_at`, which the plain note form doesn't expose;
    - drops `parent` - documents are always tree roots, never nested under
      another note;
    - defaults a new document to Visibility.PRIVATE (Note's own default,
      shared with plain notes, stays PUBLIC - overridden here at the form
      level only, same trick NoteForm itself uses for `kind`).
    """

    class Meta:
        model = Note
        fields = ["title", "kind", "body_format", "body", "visibility", "tags", "expires_at"]
        widgets = {
            "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }
        labels = {
            "title": _("Title"),
            "body": _("Description"),
            "visibility": _("Visibility"),
            "tags": _("Tags"),
            "expires_at": _("Expires at"),
        }

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, owner=owner, **kwargs)

        self.fields["kind"].choices = DOCUMENT_KIND_CHOICES
        self.fields["kind"].label = _("Kind")

        # Documents don't participate in the note tree.
        self.fields.pop("parent", None)

        if not self.instance.pk:
            self.fields["kind"].initial = DOCUMENT_KIND_CHOICES[0][0]
            self.fields["visibility"].initial = Visibility.PRIVATE
            self.fields["visibility"].label = _("Who can view it")
            self.fields["visibility"].help_text = _("Only the owner can view it by default.")
