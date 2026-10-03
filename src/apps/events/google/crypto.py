"""Encryption at rest for Google OAuth tokens (GoogleCalendarAccount).

Keys come from settings.GOOGLE_TOKEN_ENCRYPTION_KEY - comma-separated
Fernet keys, the first encrypts and all of them decrypt, so a key can be
rotated by prepending a new one. Without it a key is derived from
SECRET_KEY, which works but ties every stored token to SECRET_KEY: rotating
that would force every user to reconnect.
"""
import base64
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

logger = logging.getLogger("apps")

_DERIVED_KEY_INFO = b"apps.events.google.tokens"


class TokenDecryptError(Exception):
    """Stored token can't be decrypted with the configured keys."""


def _derived_key():
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_DERIVED_KEY_INFO)
    return base64.urlsafe_b64encode(hkdf.derive(settings.SECRET_KEY.encode()))


def _fernet():
    keys = [key.strip() for key in (settings.GOOGLE_TOKEN_ENCRYPTION_KEY or "").split(",") if key.strip()]
    if not keys:
        if not settings.DEBUG:
            logger.warning("GOOGLE_TOKEN_ENCRYPTION_KEY is not set - Google tokens are encrypted with a SECRET_KEY-derived key")
        keys = [_derived_key()]
    return MultiFernet([Fernet(key) for key in keys])


def encrypt(value):
    if not value:
        return ""
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value):
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise TokenDecryptError("Stored Google token can't be decrypted with the configured keys") from exc
