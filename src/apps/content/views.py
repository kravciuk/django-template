from datetime import timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView
from taggit.models import Tag

from apps.attachments.enums import AttachmentKind
from apps.comments.services import thread_context
from apps.common.enums import Visibility
from apps.documents.enums import DOCUMENT_KINDS
from apps.sharing.access import can_view

from .enums import NoteKind
from .forms import NoteForm
from .models import Note
from .tasks import DEFAULT_DRAFT_RETENTION_DAYS
from .text import excerpt

HOME_NOTE_COUNT = 10
HOME_DOCUMENT_COUNT = 5
HOME_DOCUMENT_EXPIRY_WINDOW_DAYS = 30
TAG_SUGGEST_LIMIT = 10


class HomeView(ListView):
    template_name = "content/home.html"
    context_object_name = "entries"

    def get_queryset(self):
        notes = (
            Note.objects.alive()
            .filter(visibility=Visibility.PUBLIC, is_draft=False)
            .order_by("-created_at")[:HOME_NOTE_COUNT]
        )
        return [
            {
                "note": note,
                "excerpt": excerpt(note),
                # Cover if one was picked, else the first image, else none -
                # makes a photo-group note recognizable in the list.
                "cover": note.attachments.alive().filter(kind=AttachmentKind.IMAGE)
                .order_by("-is_cover", "position", "id").first(),
            }
            for note in notes
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        # Documents are personal (apps.documents.DocumentListView scopes
        # the same way) - an anonymous visitor gets neither block, rather
        # than someone else's warranties/contracts.
        if user.is_authenticated:
            documents = Note.objects.alive().filter(kind__in=DOCUMENT_KINDS, owner=user)
            now = timezone.now()
            context["recent_documents"] = documents.order_by("-created_at")[:HOME_DOCUMENT_COUNT]
            context["expiring_documents"] = documents.filter(
                expires_at__gte=now,
                expires_at__lte=now + timedelta(days=HOME_DOCUMENT_EXPIRY_WINDOW_DAYS),
            ).order_by("expires_at")[:HOME_DOCUMENT_COUNT]
        return context


class NoteDetailView(View):
    template_name = "content/note_detail.html"

    def get(self, request, public_id):
        note = get_object_or_404(Note.objects.alive(), public_id=public_id)
        if not can_view(note, request.user):
            raise Http404
        can_edit = request.user.is_authenticated and note.owner_id == request.user.id
        context = {"note": note, "can_edit": can_edit}
        if note.kind == NoteKind.NODE:
            # A hub note: show its children instead of a body/attachments.
            # Drafts are excluded the same way HomeView excludes them from
            # the home listing - a draft is a mid-autosave scratch row, not
            # a real published child yet (see Note's docstring), and can
            # otherwise linger as a duplicate-looking sibling of the note
            # the user actually finished saving (autosave race: an autosave
            # in flight when "Сохранить" is clicked creates a second row
            # instead of finishing the first). can_view still gates the
            # rest so a Node's listing respects the same visibility rules
            # as everywhere else.
            children = note.get_children().alive().filter(is_draft=False).order_by("-created_at")
            context["children"] = [child for child in children if can_view(child, request.user)]
        else:
            attachments = list(note.attachments.alive())
            context["images"] = [a for a in attachments if a.kind == AttachmentKind.IMAGE]
            context["other_files"] = [a for a in attachments if a.kind != AttachmentKind.IMAGE]
        context.update(thread_context(request, note))
        return render(request, self.template_name, context)


class DraftListView(LoginRequiredMixin, ListView):
    """Lists every abandoned autosave draft the current user still owns, so
    one can be found and resumed even without its parent (NoteFormView.get's
    auto-resume) - e.g. a top-level draft, or one under a parent that isn't
    reachable anymore. Purely a safety net: NoteFormView's own auto-resume
    already covers the common "reopened the same parent" case."""

    template_name = "content/note_drafts.html"
    context_object_name = "drafts"

    def get_queryset(self):
        return Note.objects.alive().filter(owner=self.request.user, is_draft=True).order_by("-updated_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Same lookup apps.content.tasks.cleanup_stale_drafts uses - shown so
        # the retention period displayed here can't drift out of sync with it.
        context["draft_retention_days"] = getattr(settings, "DRAFT_RETENTION_DAYS", DEFAULT_DRAFT_RETENTION_DAYS)
        return context


class NoteOwnershipMixin:
    """Shared by NoteFormView and NoteAutosaveView: resolve `public_id` to a
    live Note the current user owns, or None for a not-yet-created one."""

    def get_object(self, public_id):
        if public_id is None:
            return None
        note = get_object_or_404(Note.objects.alive(), public_id=public_id)
        if note.owner_id != self.request.user.id:
            raise PermissionDenied
        return note


def _persist_note(form, note, owner):
    """Shared create/update: places a brand-new note in the MP_Node tree via
    add_root/add_child (needs `owner`/`parent` from the form), or just saves
    in place if `note` already exists. Caller sets is_draft on form.instance
    beforehand - form.save(commit=False) never touches non-form fields.
    """
    parent = form.cleaned_data.get("parent")
    new_note = form.save(commit=False)
    if note is None:
        new_note.owner = owner
        if parent is not None:
            new_note = Note.objects.add_child(parent, instance=new_note)
        else:
            new_note = Note.objects.add_root(instance=new_note)
    else:
        new_note.save()
    form.save_m2m()
    return new_note


class NoteFormView(LoginRequiredMixin, NoteOwnershipMixin, View):
    template_name = "content/note_form.html"

    def get(self, request, public_id=None):
        note = self.get_object(public_id)
        initial = {}
        if note is None:
            # Opened from an existing note (e.g. its "Добавить заметку" nav
            # link, which carries ?parent=<public_id> - see base.html) -
            # preselect that note as the parent. Silently ignored if it
            # isn't one of the user's own alive notes, same as the form
            # field's own queryset restriction.
            parent_public_id = request.GET.get("parent")
            if parent_public_id:
                parent = Note.objects.alive().filter(owner=request.user, public_id=parent_public_id).first()
                if parent is not None:
                    initial["parent"] = parent
                    # Autosave already left an unfinished child under this
                    # same parent (e.g. the previous "Добавить объект" tab
                    # was closed before "Сохранить") - resume that one
                    # instead of silently starting yet another blank draft
                    # next to it. See content_detail's "children" filtering
                    # and NoteAutosaveView for why an orphaned draft can
                    # otherwise pile up unnoticed.
                    draft = (
                        parent.get_children().alive()
                        .filter(owner=request.user, is_draft=True)
                        .order_by("-updated_at")
                        .first()
                    )
                    if draft is not None:
                        return redirect("content:note_edit", public_id=draft.public_id)
        form = NoteForm(instance=note, owner=request.user, initial=initial)
        return render(request, self.template_name, {"form": form, "note": note})

    def post(self, request, public_id=None):
        note = self.get_object(public_id)
        form = NoteForm(request.POST, request.FILES, instance=note, owner=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "note": note})

        # An explicit "Сохранить" always finalizes the note - whether it's
        # brand new, resuming an autosaved draft (same row, see
        # NoteAutosaveView), or a plain edit of an already-published note.
        form.instance.is_draft = False
        new_note = _persist_note(form, note, request.user)

        remove_ids = [a.pk for a in form.cleaned_data.get("remove_attachments") or []]
        if remove_ids:
            new_note.attachments.alive().filter(pk__in=remove_ids).soft_delete()

        for uploaded_file in form.cleaned_data.get("attachments") or []:
            new_note.attachments.create(owner=request.user, file=uploaded_file)

        return redirect("content:note_detail", public_id=new_note.public_id)


class NoteAutosaveView(LoginRequiredMixin, NoteOwnershipMixin, View):
    """Background save target for note_form.html's autosave JS
    (static/content/js/note_autosave.js). Persists the same Note row the
    form represents - a brand-new note is born as a draft (is_draft=True,
    owner-only until the real "Сохранить", see can_view/HomeView); autosaving
    an existing note (draft or already published) just updates it in place
    without touching is_draft. Doesn't touch attachments - those stay a
    final-submit-only concern.
    """

    def post(self, request, public_id=None):
        note = self.get_object(public_id)
        form = NoteForm(request.POST, instance=note, owner=request.user)
        # Only loosen the genuinely free-typed fields - the user may not
        # have written a title/body yet. kind/body_format/visibility stay
        # required: their <select> widgets always submit a concrete value,
        # and accepting '' for them would silently overwrite the model's
        # defaults with an empty, invalid choice via form.save(commit=False).
        for name in ("title", "body"):
            if name in form.fields:
                form.fields[name].required = False
        if not form.is_valid():
            return JsonResponse({"ok": False, "errors": form.errors}, status=400)

        if note is None:
            form.instance.is_draft = True
        new_note = _persist_note(form, note, request.user)

        return JsonResponse({
            "ok": True,
            "public_id": str(new_note.public_id),
            "edit_url": reverse("content:note_edit", args=[new_note.public_id]),
            "autosave_url": reverse("content:note_autosave_edit", args=[new_note.public_id]),
            "saved_at": new_note.updated_at.isoformat(),
        })


@login_required
def tag_suggest(request):
    """Existing tag names matching `q` - lets the tag-input JS offer reuse
    instead of the user retyping a near-duplicate. Global across all notes'
    tags (not scoped to the current user) - see plan doc for the tradeoff.
    """
    query = (request.GET.get("q") or "").strip()
    if not query:
        return JsonResponse({"results": []})
    tags = Tag.objects.filter(name__icontains=query).order_by("name").values_list("name", flat=True)
    return JsonResponse({"results": list(tags[:TAG_SUGGEST_LIMIT])})
