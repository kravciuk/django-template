from constance import config

from .formats import active_display_formats


def account_allow_signup(request):
    """Exposes the ACCOUNT_ALLOW_SIGNUP constance flag (core/settings/constance.py)
    to templates/base.html, which hides the "Sign up" nav link while
    registration is closed.
    """
    return {"ACCOUNT_ALLOW_SIGNUP": config.ACCOUNT_ALLOW_SIGNUP}


def display_formats(request):
    """The request's effective date/time formats (apps.users.formats), which
    templates/base.html hands to the JS side as <html data-*> attributes."""
    return {"display_formats": active_display_formats()}
