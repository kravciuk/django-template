"""Which OAuth client (client id + secret) a user connects through, and
which one refreshes a connected account's tokens.

A user's own client (GoogleOAuthClient, from their own Google Cloud
project) wins; the site-wide one from settings (GOOGLE_OAUTH_CLIENT_ID/
SECRET) is the fallback. Tokens can only be refreshed through the client
they were issued to, so a connected account remembers its client id
(GoogleCalendarAccount.oauth_client_id, "" = the site-wide client).
"""
import logging
from dataclasses import dataclass

from django.conf import settings

from ..models import GoogleOAuthClient
from .crypto import TokenDecryptError

logger = logging.getLogger("apps")


@dataclass(frozen=True)
class OAuthClient:
    client_id: str
    client_secret: str
    own: bool = False   # the user's own client, not the site-wide one


def site_client():
    if settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET:
        return OAuthClient(settings.GOOGLE_OAUTH_CLIENT_ID, settings.GOOGLE_OAUTH_CLIENT_SECRET)
    return None


def own_client(user):
    """The user's own client, or None if not set (or its secret can't be
    decrypted any more)."""
    record = GoogleOAuthClient.objects.filter(user=user).first()
    if record is None or not record.client_id:
        return None
    try:
        secret = record.get_client_secret()
    except TokenDecryptError:
        logger.warning("Google OAuth client secret can't be decrypted", extra={"user": user.pk})
        return None
    return OAuthClient(record.client_id, secret, own=True) if secret else None


def for_user(user):
    """The client a new connection goes through, or None if there's none."""
    return own_client(user) or site_client()


def by_id(user, client_id):
    """The user's own or the site-wide client with this id, or None."""
    for candidate in (own_client(user), site_client()):
        if candidate is not None and candidate.client_id == client_id:
            return candidate
    return None


def for_account(account):
    """The client account's tokens were issued to, or None if it's gone
    (the user replaced their own client, the site's was changed) - the user
    has to reconnect then."""
    if not account.oauth_client_id:
        return site_client()
    return by_id(account.user, account.oauth_client_id)
