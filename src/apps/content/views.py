from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView
from taggit.models import Tag

from apps.attachments.enums import AttachmentKind
from apps.common.enums import Visibility
from apps.sharing.access import can_view

from .forms import NoteForm
from .models import Note
from .text import excerpt

HOME_NOTE_COUNT = 10
TAG_SUGGEST_LIMIT = 10


class HomeView(ListView):
    template_name = "content/home.html"
    context_object_name = "entries"

    def get_queryset(self):
        notes = Note.objects.alive().filter(visibility=Visibility.PUBLIC).order_by("-created_at")[:HOME_NOTE_COUNT]
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


class NoteDetailView(View):
    template_name = "content/note_detail.html"

    def get(self, request, public_id):
        note = get_object_or_404(Note.objects.alive(), public_id=public_id)
        if not can_view(note, request.user):
            raise Http404
        can_edit = request.user.is_authenticated and note.owner_id == request.user.id
        attachments = list(note.attachments.alive())
        context = {
            "note": note,
            "can_edit": can_edit,
            "images": [a for a in attachments if a.kind == AttachmentKind.IMAGE],
            "other_files": [a for a in attachments if a.kind != AttachmentKind.IMAGE],
        }
        return render(request, self.template_name, context)


class NoteFormView(LoginRequiredMixin, View):
    template_name = "content/note_form.html"

    def get_object(self, public_id):
        if public_id is None:
            return None
        note = get_object_or_404(Note.objects.alive(), public_id=public_id)
        if note.owner_id != self.request.user.id:
            raise PermissionDenied
        return note

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
        form = NoteForm(instance=note, owner=request.user, initial=initial)
        return render(request, self.template_name, {"form": form, "note": note})

    def post(self, request, public_id=None):
        note = self.get_object(public_id)
        form = NoteForm(request.POST, request.FILES, instance=note, owner=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "note": note})

        parent = form.cleaned_data.get("parent")
        new_note = form.save(commit=False)

        if note is None:
            new_note.owner = request.user
            if parent is not None:
                new_note = Note.objects.add_child(parent, instance=new_note)
            else:
                new_note = Note.objects.add_root(instance=new_note)
        else:
            new_note.save()

        form.save_m2m()

        remove_ids = [a.pk for a in form.cleaned_data.get("remove_attachments") or []]
        if remove_ids:
            new_note.attachments.alive().filter(pk__in=remove_ids).soft_delete()

        for uploaded_file in form.cleaned_data.get("attachments") or []:
            new_note.attachments.create(owner=request.user, file=uploaded_file)

        return redirect("content:note_detail", public_id=new_note.public_id)


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
