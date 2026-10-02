from datetime import datetime, time

from constance import config
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext
from django_ckeditor_5.widgets import CKEditor5Widget

from apps.attachments.forms import MultipleFileField
from apps.attachments.models import Attachment
from apps.attachments.validators import validate_upload_extension, validate_upload_size
from apps.common.enums import ContentFormat
from apps.events.recurrence import FREQUENCIES, all_day_date, all_day_moment, build_rrule, parse_simple

from .enums import NoteKind
from .models import Note

DEFAULT_MAX_FILES_PER_UPLOAD = 10
DEFAULT_NOTE_COLOR = "#3a3f44"
CUSTOM_RECURRENCE = "CUSTOM"
# HTML datetime-local wants "YYYY-MM-DDTHH:MM".
DATETIME_LOCAL_FORMAT = "%Y-%m-%dT%H:%M"

# "Remind me" options (minutes before the event) - see
# apps.events.reminders. Documents get their own list (DocumentForm).
REMIND_CHOICES = [
    ("", _("No reminder")),
    (0, _("At the start")),
    (15, _("15 minutes before")),
    (60, _("1 hour before")),
    (24 * 60, _("1 day before")),
    (7 * 24 * 60, _("1 week before")),
]
# Calendar fields render last, in this order.
CALENDAR_FIELD_ORDER = [
    "starts_at", "expires_at", "all_day", "repeat", "repeat_interval", "repeat_until",
    "remind_minutes_before", "color", "use_default_color",
]
REPEAT_CHOICES = [
    ("", _("Does not repeat")),
    ("DAILY", _("Daily")),
    ("WEEKLY", _("Weekly")),
    ("MONTHLY", _("Monthly")),
    ("YEARLY", _("Yearly")),
]

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
# offers the two kinds it actually knows how to present. Labels reuse the
# enum's own (already translated) choices instead of repeating literals here.
FORM_NOTE_KIND_CHOICES = [
    (NoteKind.NOTE, NoteKind.NOTE.label),
    (NoteKind.ALBUM, NoteKind.ALBUM.label),
    # A hidden hub note - see NoteKind.NODE / Note.save(). Its visibility is
    # forced to UNLISTED on save regardless of what the form's `visibility`
    # field ends up submitting.
    (NoteKind.NODE, NoteKind.NODE.label),
    # A quick calendar note (apps.events) - offered so one opened from the
    # calendar's "Open full form" still validates here.
    (NoteKind.EVENT, NoteKind.EVENT.label),
]


def remind_choices_with(choices, value):
    """`choices` plus `value` if it's a custom offset not in the list (set
    via the API/admin), so editing the note doesn't silently drop it."""
    if value is None or any(choice == value for choice, _label in choices):
        return choices
    return [*choices, (value, ngettext("%(count)d minute before", "%(count)d minutes before", value) % {"count": value})]


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
        label=_("Parent note"),
        help_text=_("Leave empty to create a top-level note."),
    )
    attachments = MultipleFileField(
        required=False,
        label=_("Files"),
        help_text=_("You can select several files at once."),
        validators=[validate_upload_size, validate_upload_extension],
    )
    remove_attachments = forms.ModelMultipleChoiceField(
        queryset=Attachment.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label=_("Remove files"),
    )

    class Meta:
        model = Note
        fields = [
            "title", "kind", "body_format", "body", "visibility", "tags",
            "starts_at", "expires_at", "all_day", "color", "remind_minutes_before",
        ]
        widgets = {
            "starts_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DATETIME_LOCAL_FORMAT),
            "expires_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format=DATETIME_LOCAL_FORMAT),
            "color": forms.TextInput(attrs={"type": "color", "class": "form-control-color"}),
        }
        labels = {
            "starts_at": _("Starts at"),
            "expires_at": _("Ends at"),
            "remind_minutes_before": _("Remind me"),
        }
        help_texts = {
            "starts_at": _("Set a start and/or an end to show this note on the calendar."),
        }

    def __init__(self, *args, owner=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["kind"].choices = FORM_NOTE_KIND_CHOICES
        self._init_calendar_fields()

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

    def _init_calendar_fields(self):
        """Calendar placement fields (apps.events). Only set up the ones this
        form actually has - DocumentForm reuses this __init__ with a
        narrower Meta.fields."""
        instance = self.instance
        if "remind_minutes_before" in self.fields:
            self.fields["remind_minutes_before"] = forms.TypedChoiceField(
                label=_("Remind me"),
                choices=remind_choices_with(REMIND_CHOICES, instance.remind_minutes_before),
                coerce=int, empty_value=None, required=False,
            )
        if "color" in self.fields:
            self.fields["use_default_color"] = forms.BooleanField(
                label=_("Use the default calendar color"), required=False,
                initial=not instance.color,
            )
            if not instance.color:
                self.initial["color"] = getattr(config, "EVENTS_NOTE_COLOR", DEFAULT_NOTE_COLOR)
        if "starts_at" in self.fields:
            simple = parse_simple(instance.recurrence)
            repeat_choices = list(REPEAT_CHOICES)
            if simple is None:
                # A rule the simple controls can't express (e.g. imported) -
                # keep it unless the user picks something else.
                repeat_choices.append((CUSTOM_RECURRENCE, _("Custom: %(rule)s") % {"rule": instance.recurrence}))
            self.fields["repeat"] = forms.ChoiceField(label=_("Repeat"), choices=repeat_choices, required=False)
            self.fields["repeat_interval"] = forms.IntegerField(
                label=_("Every"), min_value=1, max_value=365, required=False,
                help_text=_("1 = every day/week/month/year, 2 = every other one, ..."),
            )
            self.fields["repeat_until"] = forms.DateField(
                label=_("Repeat until"), required=False,
                widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            )
            if simple is None:
                self.initial.setdefault("repeat", CUSTOM_RECURRENCE)
            elif simple:
                self.initial.setdefault("repeat", simple["freq"])
                self.initial.setdefault("repeat_interval", simple["interval"])
                self.initial.setdefault("repeat_until", simple["until"])
            # All-day values are stored as UTC midnight - show them as that
            # *date* at 00:00 instead of converting to the viewer's zone.
            if instance.all_day:
                for name in ("starts_at", "expires_at"):
                    value = getattr(instance, name)
                    if value is not None:
                        self.initial[name] = datetime.combine(all_day_date(value), time.min)
            self.order_fields([
                *[name for name in self.fields if name not in CALENDAR_FIELD_ORDER],
                *CALENDAR_FIELD_ORDER,
            ])

    def main_fields(self):
        """Everything except the calendar fields - note_form.html renders
        these openly and tucks calendar_fields() into a collapsible block."""
        return [field for field in self if field.name not in CALENDAR_FIELD_ORDER]

    def calendar_fields(self):
        return [field for field in self if field.name in CALENDAR_FIELD_ORDER]

    @property
    def calendar_open(self):
        """Whether the collapsible calendar block starts expanded: the note
        is already on the calendar, or one of its fields has an error that
        would otherwise be hidden."""
        names = [name for name in CALENDAR_FIELD_ORDER if name in self.fields]
        if self.is_bound and any(self.errors.get(name) for name in names):
            return True
        instance = self.instance
        return bool(
            instance.starts_at or instance.expires_at or instance.recurrence
            or instance.remind_minutes_before is not None
        )

    def clean(self):
        cleaned_data = super().clean()
        starts_at = cleaned_data.get("starts_at")
        expires_at = cleaned_data.get("expires_at")
        if "all_day" in self.fields and cleaned_data.get("all_day"):
            # Keep the chosen *date* (in the viewer's zone), drop the time.
            if starts_at is not None:
                starts_at = cleaned_data["starts_at"] = all_day_moment(timezone.localtime(starts_at).date())
            if expires_at is not None:
                expires_at = cleaned_data["expires_at"] = all_day_moment(timezone.localtime(expires_at).date())
        if "starts_at" in self.fields and starts_at and expires_at and expires_at < starts_at:
            self.add_error("expires_at", gettext("The end can't be before the start."))
        if "use_default_color" in self.fields and cleaned_data.get("use_default_color"):
            cleaned_data["color"] = ""
        if "repeat" in self.fields:
            self._clean_recurrence(cleaned_data, starts_at or expires_at)
        return cleaned_data

    def _clean_recurrence(self, cleaned_data, anchor):
        repeat = cleaned_data.get("repeat") or ""
        if repeat == CUSTOM_RECURRENCE:
            return  # leave instance.recurrence as it was
        if repeat and anchor is None:
            self.add_error("repeat", gettext("A repeating note needs a start or an end date."))
            return
        if repeat not in ("", *FREQUENCIES):
            self.add_error("repeat", gettext("Unknown repeat option."))
            return
        self.instance.recurrence = build_rrule(
            repeat, cleaned_data.get("repeat_interval") or 1, cleaned_data.get("repeat_until"),
        ) if repeat else ""

    def clean_attachments(self):
        files = self.cleaned_data.get("attachments") or []
        max_files = getattr(config, "ATTACHMENTS_MAX_FILES_PER_UPLOAD", DEFAULT_MAX_FILES_PER_UPLOAD)
        if len(files) > max_files:
            raise ValidationError(
                ngettext(
                    "You can upload at most %(max_files)d file at a time.",
                    "You can upload at most %(max_files)d files at a time.",
                    max_files,
                )
                % {"max_files": max_files}
            )
        return files
