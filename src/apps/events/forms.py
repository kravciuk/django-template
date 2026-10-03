from django import forms
from django.utils.translation import gettext_lazy as _

from .models import GoogleCalendarAccount


class GoogleOAuthClientForm(forms.Form):
    """The user's own OAuth client. The secret is never shown back: leaving
    it blank keeps the stored one (only possible for the same client id)."""

    client_id = forms.CharField(
        label=_("Client ID"), max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "autocomplete": "off", "spellcheck": "false"}),
    )
    client_secret = forms.CharField(
        label=_("Client secret"), required=False,
        help_text=_("Leave blank to keep the stored secret."),
        widget=forms.PasswordInput(attrs={"class": "form-control", "autocomplete": "new-password"}, render_value=False),
    )

    def __init__(self, *args, current=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.current = current
        if current is None:
            self.fields["client_secret"].help_text = ""

    def clean_client_id(self):
        return self.cleaned_data["client_id"].strip()

    def clean_client_secret(self):
        return self.cleaned_data["client_secret"].strip()

    def clean(self):
        cleaned = super().clean()
        client_id = cleaned.get("client_id")
        keeps_secret = self.current is not None and self.current.client_id == client_id
        if client_id and not cleaned.get("client_secret") and not keeps_secret:
            self.add_error("client_secret", _("Enter the client secret of this client ID."))
        return cleaned


class GoogleCalendarSettingsForm(forms.Form):
    """Settings of a connected Google Calendar. `calendars` is the live
    calendarList (owned calendars only) fetched by the view."""

    calendar_id = forms.ChoiceField(
        label=_("Calendar"),
        help_text=_("Events are synced with this calendar. Switching it removes the events this site created "
                    "from the old calendar; notes imported from it stay here."),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    sync_direction = forms.ChoiceField(
        label=_("Sync direction"),
        choices=GoogleCalendarAccount.SyncDirection.choices,
        help_text=_("Both ways: changes on either side are applied to the other. "
                    "Only from Google: events from Google appear here, nothing is written to Google. "
                    "Only to Google: your notes appear in Google as a read-only copy - events created in Google "
                    "aren't imported, and changes made there to the copied events are undone."),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    sync_enabled = forms.BooleanField(
        label=_("Sync enabled"), required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    push_documents = forms.BooleanField(
        label=_("Include document expiry dates"), required=False,
        help_text=_("Warranty and contract deadlines appear in Google as all-day events. "
                    "Changes made to them in Google are overwritten. Only when syncing to Google."),
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, calendars=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.calendars = {item["id"]: item.get("summaryOverride") or item.get("summary") or item["id"] for item in calendars}
        self.fields["calendar_id"].choices = list(self.calendars.items())

    def calendar_summary(self):
        return self.calendars.get(self.cleaned_data["calendar_id"], "")
