from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.utils import timezone

from .utils import get_client_ip


@receiver(user_logged_in)
def update_last_login_info(sender, request, user, **kwargs):
    """Track last_login_date/last_login_ip on every session-based login.

    Fires for session/admin login and any future view calling
    django.contrib.auth.login(). SimpleJWT's default token-obtain view does
    not call login() and won't trigger this signal - wiring that up is a
    separate task for when a JWT login view is added.
    """
    user.last_login_date = timezone.now()
    user.last_login_ip = get_client_ip(request)
    user.save(update_fields=["last_login_date", "last_login_ip"])
