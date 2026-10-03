import zoneinfo

from django.utils import timezone

from . import formats


def user_zoneinfo(user):
    """The user's own IANA zone as a ZoneInfo, or None if unset/invalid
    (callers then fall back to settings.TIME_ZONE). Shared by the request
    middleware below and background code that formats times for a specific
    recipient (apps.events.tasks)."""
    name = getattr(user, "timezone", "") or ""
    if not name:
        return None
    try:
        return zoneinfo.ZoneInfo(name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        return None


class UserTimezoneMiddleware:
    """Activates the logged-in user's profile time zone for the request, so
    form widgets (datetime-local), templates and timezone.localtime() all
    show local wall-clock time while the DB keeps storing UTC. Anonymous
    users and users without a zone get settings.TIME_ZONE.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        tz = user_zoneinfo(user) if user is not None and user.is_authenticated else None
        if tz is not None:
            timezone.activate(tz)
        else:
            timezone.deactivate()
        return self.get_response(request)


class UserFormatsMiddleware:
    """Activates the logged-in user's date/time display preferences
    (apps.users.formats) for the request; anonymous users get the active
    language's own Django formats."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            formats.activate(user)
        else:
            formats.deactivate()
        return self.get_response(request)
