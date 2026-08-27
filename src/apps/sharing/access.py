from apps.common.enums import Visibility

from .models import ShareLink


def resolve_token(token, raw_password=None):
    """Look up a share link by token and validate it (active, not expired,
    not over its use limit, and password check if one is set).

    Returns the ShareLink on success, else None. Does not call
    register_use() - callers should only do that after actually serving the
    object, not on every lookup attempt.
    """
    try:
        link = ShareLink.objects.select_related("content_type").get(token=token)
    except ShareLink.DoesNotExist:
        return None
    if not link.is_valid():
        return None
    if link.has_password and not link.check_password(raw_password or ""):
        return None
    return link


def can_view(obj, user, *, share_link=None):
    """The single point of truth for the four visibility levels.

    Every access path (admin now, DRF/HTMX later) must call this rather
    than re-implementing the rules.
    """
    is_owner = user is not None and getattr(user, "is_authenticated", False) and obj.owner_id == user.id
    if is_owner:
        return True

    # A draft (autosaved, never explicitly published - see apps/content's
    # NoteFormView/NoteAutosaveView) is owner-only regardless of whatever
    # `visibility` it happens to carry mid-edit. Only Note has this field
    # today, hence getattr with a default.
    if getattr(obj, "is_draft", False):
        return False

    visibility = obj.visibility
    if visibility == Visibility.PUBLIC:
        return True
    if visibility == Visibility.UNLISTED:
        return True  # reachable via its own unguessable public_id link
    if visibility == Visibility.SHARED:
        return share_link is not None and share_link.is_valid()
    # Visibility.PRIVATE (and any unexpected value) - owner only, already
    # handled above.
    return False
