from django.core.paginator import Paginator

from .forms import CommentForm
from .models import get_max_depth
from .registry import target_kind_for

TOP_LEVEL_PAGE_SIZE = 20


def thread_context(request, target, *, page=None, form=None):
    """Context comments/_thread.html needs to render a target's comment
    thread. Shared by apps.content.views.NoteDetailView/apps.documents.
    views.DocumentDetailView (via a plain `{% include %}` - no extra
    request round-trip on the initial page load) and by
    apps.comments.views.CommentThreadView (hit directly only by the
    thread's own pagination links).

    `form` lets a create-view substitute its own invalid, error-carrying
    form instead of a fresh blank one after a failed submit. `page` lets a
    create-view jump straight to the last page (where the just-posted
    comment now lives) after a successful one.
    """
    kind = target_kind_for(target)
    # Not .alive(): a soft-deleted comment with alive replies underneath it
    # must stay queryable so the recursive walk in comments/_comment.html
    # can still reach those replies and render the parent as a "[deleted]"
    # placeholder rather than silently orphaning its whole subtree. A
    # trashed comment with no replies at all just renders as an empty,
    # invisible node - see comments/_comment.html.
    top_level = target.comments.filter(parent__isnull=True)
    paginator = Paginator(top_level, TOP_LEVEL_PAGE_SIZE)
    page_number = page if page is not None else request.GET.get("page")
    return {
        "target": target,
        "target_kind": kind.slug,
        "comments_page": paginator.get_page(page_number),
        "comment_form": form if form is not None else (CommentForm() if request.user.is_authenticated else None),
        "max_depth": get_max_depth(),
    }
