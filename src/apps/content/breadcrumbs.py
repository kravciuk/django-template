"""Breadcrumb-trail construction for the shared header (see
templates/base.html + apps.content.templatetags.header_tags).

A crumb is a plain dict: {"label": str, "url": str | None}. `url=None` marks
the current page - the header component renders it unlinked, as the last,
non-clickable item.
"""

from django.urls import reverse
from django.utils.translation import gettext as _


def _home_crumb(request):
    # The home crumb carries no label - the header renders it as a house
    # icon only (see Main.dc.html / Mobile.dc.html, the approved mockup).
    url = reverse("content:home")
    # Don't link the crumb for the page the user is already on - matches
    # how every other trailing crumb below behaves for its own page.
    is_home = request.resolver_match and request.resolver_match.view_name == "content:home"
    return {"label": "", "url": None if is_home else url}


def build_breadcrumbs(request, note=None):
    """The breadcrumb trail for the current request.

    `note` is whatever Note instance the calling view's own context already
    exposes (content:note_detail/note_edit's `note`, documents:detail/edit's
    `document` - both are just Note rows, see apps.documents). When one is
    given, the trail is its full ancestor chain (root..parent, via
    treebeard's get_ancestors()) followed by the note itself, unlinked, last.
    Without one, fall back to a single section-root crumb keyed off the
    current URL's app namespace.
    """
    crumbs = [_home_crumb(request)]

    if note is not None:
        for ancestor in note.get_ancestors():
            crumbs.append({
                "label": ancestor.title,
                "url": reverse("content:note_detail", args=[ancestor.public_id]),
            })
        crumbs.append({"label": note.title, "url": None})
        return crumbs

    app_name = request.resolver_match.app_name if request.resolver_match else None
    if app_name == "documents":
        crumbs.append({"label": _("Документы"), "url": None})
    return crumbs
