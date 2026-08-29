from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views import View

from apps.sharing.access import can_view
from libs.utils import get_client_ip

from .forms import CommentForm
from .models import Comment, get_max_depth
from .registry import get_target_kind, target_kind_for
from .services import thread_context

THREAD_TEMPLATE = "comments/_thread.html"
COMMENT_TEMPLATE = "comments/_comment.html"
FORM_TEMPLATE = "comments/_comment_form.html"


def _resolve_target(target_kind_slug, public_id):
    kind = get_target_kind(target_kind_slug)
    if kind is None:
        raise Http404
    return get_object_or_404(kind.get_queryset(), public_id=public_id)


def _require_login(request):
    if not request.user.is_authenticated:
        raise PermissionDenied


def _new_comment(request, target, parent, body):
    """Builds and validates (but does not save) a new Comment. Validation
    goes through full_clean(), which calls Comment.clean() - the single
    source of truth for the depth cap and the same-object-as-parent rule -
    so an over-depth reply surfaces as a ValidationError here instead of a
    raw IntegrityError from the DB CheckConstraint.
    """
    comment = Comment(
        content_type=ContentType.objects.get_for_model(target),
        object_id=target.pk,
        parent=parent,
        owner=request.user,
        body=body,
        ip=get_client_ip(request),
    )
    comment.full_clean()
    return comment


class CommentThreadView(View):
    """GET-only. The initial page load never hits this - NoteDetailView/
    DocumentDetailView build the same context themselves via
    services.thread_context() and include comments/_thread.html directly.
    This view is only routed to by that template's own pagination links,
    so it must re-check can_view() independently rather than relying on
    the wrapping page having already done so.
    """

    def get(self, request, target_kind, public_id):
        target = _resolve_target(target_kind, public_id)
        if not can_view(target, request.user):
            raise Http404
        return render(request, THREAD_TEMPLATE, thread_context(request, target))


class CommentCreateView(View):
    """POST-only, htmx-only (the compose form's hx-post) - never reached
    via a full-page GET, so an unauthenticated POST gets a plain
    PermissionDenied (403) instead of LoginRequiredMixin's redirect to
    LOGIN_URL, which would make htmx swap the admin login page's HTML into
    the comment thread.
    """

    def post(self, request, target_kind, public_id):
        _require_login(request)
        target = _resolve_target(target_kind, public_id)
        if not can_view(target, request.user):
            raise Http404

        form = CommentForm(request.POST)
        if form.is_valid():
            try:
                comment = _new_comment(request, target, None, form.cleaned_data["body"])
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                comment.save()
                return render(request, THREAD_TEMPLATE, thread_context(request, target, page="last"))

        # Invalid input, or a depth/target ValidationError caught above:
        # re-render the same fragment with the same bound/error-carrying
        # form, status 200 (not 400) - matches every other form view in
        # this repo (e.g. apps.content.views.NoteFormView.post()) and is
        # required for htmx to actually swap the response in (its default
        # config does not swap non-2xx responses).
        return render(request, THREAD_TEMPLATE, thread_context(request, target, form=form))


class CommentReplyView(View):
    """GET renders the inline reply-form fragment; POST creates the reply.
    Both htmx-only, both require login via the same manual
    check/rationale as CommentCreateView.
    """

    def _get_parent(self, request, pk):
        parent = get_object_or_404(Comment.objects.alive(), pk=pk)
        target = parent.target
        if target is None or target_kind_for(target) is None or not can_view(target, request.user):
            raise Http404
        return parent

    def get(self, request, pk):
        _require_login(request)
        parent = self._get_parent(request, pk)
        return render(request, FORM_TEMPLATE, {
            "form": CommentForm(),
            "action_url_name": "comments:reply",
            "comment_pk": parent.pk,
        })

    def post(self, request, pk):
        _require_login(request)
        parent = self._get_parent(request, pk)

        form = CommentForm(request.POST)
        if form.is_valid():
            try:
                reply = _new_comment(request, parent.target, parent, form.cleaned_data["body"])
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                reply.save()
                # Out-of-band swap: append the new node into the parent's
                # replies container. A reply never affects pagination, so
                # there's no need to refresh the whole thread. The rest of
                # the response body is empty, which - via the reply form's
                # own hx-target/hx-swap="innerHTML" - clears/closes the
                # inline reply box that submitted this request.
                return render(request, COMMENT_TEMPLATE, {
                    "comment": reply,
                    "target_kind": target_kind_for(parent.target).slug,
                    "max_depth": get_max_depth(),
                    "oob_swap": f"beforeend:#comment-replies-{parent.pk}",
                })

        return render(request, FORM_TEMPLATE, {
            "form": form,
            "action_url_name": "comments:reply",
            "comment_pk": parent.pk,
        })


class _OwnCommentMixin:
    """Shared by CommentEditView/CommentDeleteView: resolve `pk` to a
    live, alive Comment the current user owns - mirrors
    apps.content.views.NoteOwnershipMixin/apps.documents.views.
    DocumentOwnershipMixin, just keyed by the comment's own pk (Comment
    has no public_id).
    """

    def get_comment(self, request, pk):
        _require_login(request)
        comment = get_object_or_404(Comment.objects.alive(), pk=pk)
        target = comment.target
        if target is None or not can_view(target, request.user):
            raise Http404
        if comment.owner_id != request.user.id:
            raise PermissionDenied
        return comment


class CommentEditView(_OwnCommentMixin, View):
    """GET opens an inline edit form in place of the comment's body; POST
    applies the edit. Both re-render #comment-{pk} outerHTML - editing
    never changes the tree shape, so a single-node swap is always enough
    and always correct.
    """

    def get(self, request, pk):
        comment = self.get_comment(request, pk)
        return render(request, COMMENT_TEMPLATE, {
            "comment": comment,
            "target_kind": target_kind_for(comment.target).slug,
            "max_depth": get_max_depth(),
            "editing": True,
            "edit_form": CommentForm(instance=comment),
        })

    def post(self, request, pk):
        comment = self.get_comment(request, pk)
        form = CommentForm(request.POST, instance=comment)
        context = {
            "comment": comment,
            "target_kind": target_kind_for(comment.target).slug,
            "max_depth": get_max_depth(),
        }
        if form.is_valid():
            form.save()  # Comment.save()'s _original_body diff stamps edited_at itself.
            return render(request, COMMENT_TEMPLATE, context)
        context.update({"editing": True, "edit_form": form})
        return render(request, COMMENT_TEMPLATE, context)


class CommentDeleteView(_OwnCommentMixin, View):
    """POST-only. Soft-deletes - never cascades to replies (Comment has
    no such cascade behaviour, by design). If the comment still has alive
    replies, re-renders #comment-{pk} as the "[deleted]" placeholder so
    the subtree underneath isn't orphaned; otherwise returns an empty
    body, which with hx-swap="outerHTML" removes the node from the DOM.
    """

    def post(self, request, pk):
        comment = self.get_comment(request, pk)
        comment.soft_delete()
        # Not .alive(): a reply nested further down may itself be alive
        # even if it's several levels deep under other trashed comments -
        # keep the placeholder (and the whole subtree under it) rather
        # than only checking direct children.
        if comment.replies.exists():
            return render(request, COMMENT_TEMPLATE, {
                "comment": comment,
                "target_kind": target_kind_for(comment.target).slug,
                "max_depth": get_max_depth(),
            })
        return HttpResponse("")
