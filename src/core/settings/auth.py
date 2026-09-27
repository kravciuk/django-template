"""django-allauth: user-facing login/logout/signup/password-reset/2FA.

Split out from base.py the same way rest.py/celery.py are, and imported from
there. See docs/architecture/settings.md and docs/apps/users.md for the
full picture.
"""

import os


def _env(key, default=None):
    return os.environ.get(key, default)


def _env_bool(key, default=False):
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# allauth wiring
# ---------------------------------------------------------------------------

ACCOUNT_ADAPTER = "apps.users.adapter.AccountAdapter"

# Both a username and an email work as the login identifier - the project
# already has usernames (createsuperuser etc.) and email isn't guaranteed
# unique on the User model itself (allauth tracks/verifies email in its own
# EmailAddress table instead, see ACCOUNT_UNIQUE_EMAIL below).
ACCOUNT_LOGIN_METHODS = {"username", "email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "username*", "password1*", "password2*"]
ACCOUNT_UNIQUE_EMAIL = True

# Whether registration is open lives in constance instead of a static
# setting (core/settings/constance.py, ACCOUNT_ALLOW_SIGNUP) - it's a
# runtime call (flip it on/off from /admin/constance/config/ once the
# multi-user-migration prerequisites are actually closed), not a deploy-time
# one. apps/users/adapter.py reads it from `constance.config`.
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION = True
ACCOUNT_CONFIRM_EMAIL_ON_GET = False

# The "Remember me" checkbox on the login form - None makes it visible and
# lets the user pick (checked: persistent cookie, unchecked: session cookie
# that dies when the browser closes).
ACCOUNT_SESSION_REMEMBER = None
ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE = False
ACCOUNT_LOGOUT_ON_GET = False

# Explicit rather than relying on allauth's own defaults, so the actual
# limits are visible in this repo. Each value is one or more comma-separated
# "<count>/<period>/<ip|user|key>" rules (ALL must pass) - not a single rule
# with several "per" dimensions, so a combined IP+key limit needs its own
# full rule on each side of the comma.
ACCOUNT_RATE_LIMITS = {
    "login_failed": "5/5m/ip,5/5m/key",
    "signup": "5/h/ip",
    "send_email": "5/5m/key,3/m/ip",
    "reauthenticate": "5/5m/user",
    "reset_password": "5/5m/ip,3/1m/key",
    "reset_password_from_key": "10/5m/ip",
    "change_email": "5/h/user",
    "manage_email": "10/m/user",
}

MFA_SUPPORTED_TYPES = ["totp", "webauthn", "recovery_codes"]
MFA_TOTP_ISSUER = _env("MFA_TOTP_ISSUER", "django-template")

# Passkeys (WebAuthn) as an additional login method, on top of
# username/email+password. This only covers the browser/session login flow
# (allauth's account/login.html grows a "Sign in with a passkey" button) -
# the REST JWT endpoints (/api/token/) are untouched and stay password-only.
# Signup stays closed (ACCOUNT_ALLOW_SIGNUP above), so passkey signup isn't
# enabled either - passkeys are registered from /accounts/2fa/ by an already
# logged-in user, not offered at signup.
MFA_PASSKEY_LOGIN_ENABLED = True

# WebAuthn requires a secure context (https, or the literal host "localhost")
# by spec - the browser itself refuses navigator.credentials on plain http
# otherwise. This only matters for testing over http from a non-localhost
# dev host (e.g. a LAN IP) and must never be enabled in prod.
MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN = _env_bool("MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN", False)

LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "content:home"
ACCOUNT_LOGOUT_REDIRECT_URL = "content:home"

# ---------------------------------------------------------------------------
# Email - allauth sends verification/reset/notification mails synchronously.
# There's no Celery worker in dev (see CLAUDE.md), so this stays synchronous
# for now; routing it through Celery is a separate future improvement.
# Defaulting to the console backend also closes KI-3 (no EMAIL_BACKEND meant
# Django's SMTP default silently tried localhost:25 and /health/ 500'd).
# ---------------------------------------------------------------------------

EMAIL_BACKEND = _env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = _env("EMAIL_HOST", "localhost")
EMAIL_PORT = int(_env("EMAIL_PORT", "25"))
EMAIL_HOST_USER = _env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = _env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = _env_bool("EMAIL_USE_TLS", False)
EMAIL_USE_SSL = _env_bool("EMAIL_USE_SSL", False)
DEFAULT_FROM_EMAIL = _env("DEFAULT_FROM_EMAIL", "webmaster@localhost")

# ---------------------------------------------------------------------------
# Cache - ACCOUNT_RATE_LIMITS above is enforced through Django's cache
# framework, so it needs a real shared backend, not the per-process LocMem
# default. REDIS_CACHE_URL already existed in .env.example, just unused.
# ---------------------------------------------------------------------------

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": _env("REDIS_CACHE_URL", "redis://redis:6379/1"),
    }
}
