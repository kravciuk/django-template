import zoneinfo

from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

from .formats import date_format_choices, time_format_choices

User = get_user_model()


def time_zone_choices():
    """Every IANA zone this system's tzdata knows, built per form instance
    (not baked into model choices/migrations - see User.timezone)."""
    return [("", _("Server default (UTC)")), *((name, name) for name in sorted(zoneinfo.available_timezones()))]


class ProfileForm(forms.ModelForm):
    """Editable profile fields that aren't handled by allauth's own forms.

    Username and email go through allauth's account_email/account_settings
    pages instead (they carry uniqueness/verification concerns this form
    doesn't need to duplicate).
    """

    class Meta:
        model = User
        fields = ["first_name", "last_name", "timezone", "date_format", "time_format"]
        labels = {
            "first_name": _("First name"),
            "last_name": _("Last name"),
            "timezone": _("Time zone"),
            "date_format": _("Date format"),
            "time_format": _("Time format"),
        }
        help_texts = {
            "timezone": _("Dates and times (calendar, forms, reminders) are shown in this zone."),
            "date_format": _("How dates are shown and entered across the site."),
            "time_format": _("Whether times use a 24-hour or a 12-hour (AM/PM) clock."),
        }
        # Matches apps.content.forms.apply_bootstrap_widget_classes' output
        # (form-control) - inlined here rather than imported since this form
        # only has two plain CharFields and importing that helper would pull
        # apps.users into an app-to-app dependency on apps.content.
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "timezone": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A model CharField without choices renders as a text input - swap in
        # the zone list here; ChoiceField validation rejects unknown names.
        self.fields["timezone"] = forms.ChoiceField(
            label=self.fields["timezone"].label,
            help_text=self.fields["timezone"].help_text,
            choices=time_zone_choices(),
            required=False,
            widget=forms.Select(attrs={"class": "form-select", "data-detect-time-zone": ""}),
        )
        # Same reason as `timezone`: plain model CharFields, the allowed
        # values (and their examples) live in apps.users.formats.
        for name, choices in (("date_format", date_format_choices()), ("time_format", time_format_choices())):
            self.fields[name] = forms.ChoiceField(
                label=self.fields[name].label,
                help_text=self.fields[name].help_text,
                choices=choices,
                required=False,
                widget=forms.Select(attrs={"class": "form-select"}),
            )
