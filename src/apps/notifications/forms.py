from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _

User = get_user_model()


class SendNotificationForm(forms.Form):
    """Used by NotificationAdmin's custom "Send notification" view (see
    admin.py) - lets staff pick a user and forward them a one-off message.
    `kind`/`sender` aren't exposed here: this form always sends a
    MESSAGE-kind notification from the staff member submitting it (see
    NotificationAdmin.send_view)."""

    recipient = forms.ModelChoiceField(queryset=User.objects.all(), label=_("recipient"))
    title = forms.CharField(max_length=200, label=_("title"))
    body = forms.CharField(widget=forms.Textarea, required=False, label=_("body"))
