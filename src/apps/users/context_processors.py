from constance import config


def account_allow_signup(request):
    """Exposes the ACCOUNT_ALLOW_SIGNUP constance flag (core/settings/constance.py)
    to templates/base.html, which hides the "Sign up" nav link while
    registration is closed.
    """
    return {"ACCOUNT_ALLOW_SIGNUP": config.ACCOUNT_ALLOW_SIGNUP}
