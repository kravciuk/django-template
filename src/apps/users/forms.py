from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class ProfileForm(forms.ModelForm):
    """Editable profile fields that aren't handled by allauth's own forms.

    Username and email go through allauth's account_email/account_settings
    pages instead (they carry uniqueness/verification concerns this form
    doesn't need to duplicate).
    """

    class Meta:
        model = User
        fields = ["first_name", "last_name"]
        labels = {
            "first_name": _("First name"),
            "last_name": _("Last name"),
        }
        # Matches apps.content.forms.apply_bootstrap_widget_classes' output
        # (form-control) - inlined here rather than imported since this form
        # only has two plain CharFields and importing that helper would pull
        # apps.users into an app-to-app dependency on apps.content.
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
        }
