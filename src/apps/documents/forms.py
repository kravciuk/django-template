from constance import config
from django import forms
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext

from apps.common.enums import Visibility
from apps.content.forms import NoteForm, remind_choices_with
from apps.content.models import Note

from .enums import DOCUMENT_KIND_CHOICES

DEFAULT_DOCUMENT_REMIND_DAYS = 14
# Minutes before expires_at - see apps.events.reminders. Empty = the
# EVENTS_DOCUMENT_REMIND_DAYS constance default.
DOCUMENT_REMIND_CHOICES = [
    (0, _("On the expiry date")),
    (24 * 60, _("1 day before")),
    (7 * 24 * 60, _("1 week before")),
    (30 * 24 * 60, _("30 days before")),
]


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
        fields = ["title", "kind", "body_format", "body", "visibility", "tags", "expires_at", "remind_minutes_before"]
        widgets = {
            "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }
        labels = {
            "title": _("Title"),
            "body": _("Description"),
            "visibility": _("Visibility"),
            "tags": _("Tags"),
            "expires_at": _("Expires at"),
            "remind_minutes_before": _("Remind me"),
        }

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, owner=owner, **kwargs)

        self.fields["kind"].choices = DOCUMENT_KIND_CHOICES
        self.fields["kind"].label = _("Kind")

        # Documents don't participate in the note tree.
        self.fields.pop("parent", None)

        default_days = getattr(config, "EVENTS_DOCUMENT_REMIND_DAYS", DEFAULT_DOCUMENT_REMIND_DAYS)
        default_label = (
            ngettext("Default (%(days)d day before)", "Default (%(days)d days before)", default_days)
            % {"days": default_days}
            if default_days else _("Default (no reminder)")
        )
        self.fields["remind_minutes_before"].choices = remind_choices_with(
            [("", default_label), *DOCUMENT_REMIND_CHOICES], self.instance.remind_minutes_before,
        )

        if not self.instance.pk:
            self.fields["kind"].initial = DOCUMENT_KIND_CHOICES[0][0]
            self.fields["visibility"].initial = Visibility.PRIVATE
            self.fields["visibility"].label = _("Who can view it")
            self.fields["visibility"].help_text = _("Only the owner can view it by default.")
