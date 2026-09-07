from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django_ckeditor_5.widgets import CKEditor5Widget

from apps.attachments.forms import MultipleFileField
from apps.attachments.models import Attachment
from apps.attachments.validators import validate_upload_extension, validate_upload_size
from apps.common.enums import ContentFormat

from .enums import NoteKind
from .models import Note

DEFAULT_MAX_FILES_PER_UPLOAD = 10

# Ordered (most specific first) - mirrors the explicit attrs={"class": ...}
# convention already used on individual widgets in apps/documents/filters.py,
# just applied generically here instead of repeating it per field. Checked
# via isinstance, so subclasses (e.g. MultipleFileInput < ClearableFileInput)
# pick up the same class as their base.
BOOTSTRAP_WIDGET_CLASSES = [
    (forms.CheckboxSelectMultiple, "form-check-input"),
    (forms.CheckboxInput, "form-check-input"),
    (forms.Select, "form-select"),
    ((forms.ClearableFileInput, forms.FileInput), "form-control"),
    ((forms.Textarea, forms.TextInput, forms.NumberInput, forms.EmailInput,
      forms.URLInput, forms.DateInput, forms.DateTimeInput, forms.TimeInput), "form-control"),
]


def apply_bootstrap_widget_classes(fields, skip_widgets=()):
    """Adds the matching bootstrap form-control/form-select/form-check-input
    class to every field's widget, without disturbing attrs it already has
    (e.g. DocumentForm's `type: datetime-local` on expires_at).

    `skip_widgets` lets a caller opt a widget out entirely - used for
    CKEditor5Widget and the JS-driven tag-chip widget, which style themselves.
    """
    for field in fields.values():
        widget = field.widget
        if isinstance(widget, skip_widgets):
            continue
        for widget_types, css_class in BOOTSTRAP_WIDGET_CLASSES:
            if isinstance(widget, widget_types):
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} {css_class}".strip()
                break

# The other kinds (purchase/warranty/contract/reminder) need their own
# supporting UI (expiry dates etc.) that doesn't exist yet - the model
# itself stays fully general (e.g. for admin), but this public form only
# offers the two kinds it actually knows how to present.
FORM_NOTE_KIND_CHOICES = [
    (NoteKind.NOTE, "Заметка"),
    (NoteKind.ALBUM, "Фотоальбом"),
    # A hidden hub note - see NoteKind.NODE / Note.save(). Its visibility is
    # forced to UNLISTED on save regardless of what the form's `visibility`
    # field ends up submitting.
    (NoteKind.NODE, _("Узел")),
]


class NoteForm(forms.ModelForm):
    """Public-facing create/edit form for a single Note.

    Unlike the admin's `movenodeform_factory`-based form, this one never
    moves an existing node in the tree - `parent` only matters (and is only
    shown) when creating: the view uses it to pick `add_root`/`add_child`.

    `attachments` and `remove_attachments` aren't Note fields - Attachment
    is linked via a GenericRelation, not a Note column - so both are plain
    form fields the view handles explicitly after save().
    """

    parent = forms.ModelChoiceField(
        queryset=Note.objects.none(),
        required=False,
        label="Родительская заметка",
        help_text="Оставьте пустым, чтобы создать заметку верхнего уровня.",
    )
    attachments = MultipleFileField(
        required=False,
        label="Файлы",
        help_text="Можно выбрать сразу несколько файлов.",
        validators=[validate_upload_size, validate_upload_extension],
    )
    remove_attachments = forms.ModelMultipleChoiceField(
        queryset=Attachment.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Удалить файлы",
    )

    class Meta:
        model = Note
        fields = ["title", "kind", "body_format", "body", "visibility", "tags"]

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["kind"].choices = FORM_NOTE_KIND_CHOICES

        if self.instance.pk:
            # Editing: re-parenting isn't supported by this form.
            del self.fields["parent"]
            self.fields["remove_attachments"].queryset = self.instance.attachments.alive()
        else:
            # Nothing to remove yet on a note that doesn't exist.
            del self.fields["remove_attachments"]
            if owner is not None:
                self.fields["parent"].queryset = Note.objects.alive().filter(owner=owner)

        # Same widget-by-format swap as the admin's NoteBaseForm - see
        # apps/content/admin.py for why this only takes effect on reload.
        body_format = self.data.get("body_format") or getattr(self.instance, "body_format", None) or ContentFormat.HTML
        if body_format == ContentFormat.HTML:
            self.fields["body"].widget = CKEditor5Widget(config_name="content_note")
        else:
            self.fields["body"].widget = forms.Textarea(attrs={"rows": 20, "style": "font-family: monospace;"})

        # `tags` still gets form-control below like apps/documents/filters.py's
        # DocumentFilter.tags does - tag_autocomplete.js (apps/content/static/
        # content/js) re-skins it into a chip widget once it loads, but the
        # bare input needs to look right before that JS takes over.
        apply_bootstrap_widget_classes(self.fields, skip_widgets=(CKEditor5Widget,))

    def clean_attachments(self):
        files = self.cleaned_data.get("attachments") or []
        max_files = getattr(settings, "ATTACHMENTS_MAX_FILES_PER_UPLOAD", DEFAULT_MAX_FILES_PER_UPLOAD)
        if len(files) > max_files:
            raise ValidationError(f"Можно загрузить не более {max_files} файлов за раз.")
        return files
