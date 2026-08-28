"""The shared header's data - nav state + breadcrumbs - assembled once in
base.html for every page (see React `Header` component / `header-data`
json_script). `header_context` reads `takes_context=True` so it can see
whatever `note`/`document`/`can_edit` the *page's own view* already put in
context, the same way today's plain-HTML nav already does across
{% extends %} - no other view needs to change for this to work.
"""

from django import template
from django.conf import settings
from django.urls import reverse

from apps.content.breadcrumbs import build_breadcrumbs

register = template.Library()

_ACTIVE_BY_APP = {"content": "notes", "documents": "documents"}


@register.simple_tag(takes_context=True)
def header_context(context):
    request = context["request"]
    user = request.user

    note = context.get("note") or context.get("document")
    can_edit = context.get("can_edit", False)

    add_note_url = reverse("content:note_add")
    if can_edit and note is not None:
        add_note_url = f"{add_note_url}?parent={note.public_id}"

    app_name = request.resolver_match.app_name if request.resolver_match else None

    return {
        "nav": {
            "active": _ACTIVE_BY_APP.get(app_name),
            "notes_url": reverse("content:home"),
            "documents_url": reverse("documents:list"),
            "add_note_url": add_note_url,
            "add_document_url": reverse("documents:add"),
            "login_url": f"{settings.LOGIN_URL}?next={request.path}",
            "is_authenticated": user.is_authenticated,
            "display_name": str(user) if user.is_authenticated else None,
            "initial": str(user)[:1].upper() if user.is_authenticated else None,
        },
        "breadcrumbs": build_breadcrumbs(request, note=note),
    }
