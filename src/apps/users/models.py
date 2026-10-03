from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """Custom user model extended with registration/login metadata."""

    json_data = models.JSONField(default=dict, blank=True)

    registration_ip = models.GenericIPAddressField(null=True, blank=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    registration_date = models.DateTimeField(auto_now_add=True)
    last_login_date = models.DateTimeField(null=True, blank=True)

    # IANA zone name (e.g. "Europe/Vilnius"); empty = settings.TIME_ZONE.
    # Activated per request by apps.users.middleware.UserTimezoneMiddleware -
    # the DB itself always stores UTC. No `choices` here on purpose: the
    # zone list comes from tzdata and would churn migrations; ProfileForm
    # validates it instead.
    timezone = models.CharField(_("Time zone"), max_length=64, blank=True)

    # Display preferences, see apps.users.formats: a date pattern such as
    # "d.m.Y" and the clock ("24"/"12"); empty = the active language's own
    # Django formats. No `choices` for the same reason as `timezone` -
    # ProfileForm validates them against apps.users.formats.
    date_format = models.CharField(_("Date format"), max_length=16, blank=True)
    time_format = models.CharField(_("Time format"), max_length=2, blank=True)
