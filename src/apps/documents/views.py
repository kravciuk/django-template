from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django_filters.views import FilterView
from django_tables2 import SingleTableMixin

from apps.attachments.enums import AttachmentKind
from apps.content.models import Note
from apps.sharing.access import can_view

from .enums import DOCUMENT_KINDS
from .filters import DocumentFilter
from .forms import DocumentForm
from .tables import DocumentTable

PDF_MIME_TYPE = "application/pdf"


class DocumentListView(LoginRequiredMixin, SingleTableMixin, FilterView):
    """The user's own documents - sortable/filterable via django_tables2 +
    django_filter. Scoped to the requesting user: documents default to
    Visibility.PRIVATE, so "all records" here means "all of mine", not
    every document anyone has ever made public/unlisted.
    """

    template_name = "documents/list.html"
    table_class = DocumentTable
    filterset_class = DocumentFilter
    context_object_name = "documents"

    def get_queryset(self):
        return (
            Note.objects.alive()
            .filter(kind__in=DOCUMENT_KINDS, owner=self.request.user)
            .prefetch_related("tags", "attachments")
        )


class DocumentDetailView(View):
    template_name = "documents/detail.html"

    def get(self, request, public_id):
        document = get_object_or_404(
            Note.objects.alive().filter(kind__in=DOCUMENT_KINDS), public_id=public_id,
        )
        if not can_view(document, request.user):
            raise Http404

        can_edit = request.user.is_authenticated and document.owner_id == request.user.id
        attachments = list(document.attachments.alive())
        context = {
            "document": document,
            "can_edit": can_edit,
            "images": [a for a in attachments if a.kind == AttachmentKind.IMAGE],
            "pdfs": [a for a in attachments if a.kind != AttachmentKind.IMAGE and a.mime_type == PDF_MIME_TYPE],
            "other_files": [
                a for a in attachments
                if a.kind != AttachmentKind.IMAGE and a.mime_type != PDF_MIME_TYPE
            ],
        }
        return render(request, self.template_name, context)


class DocumentOwnershipMixin:
    """Resolve `public_id` to a live document the current user owns, or
    None for a not-yet-created one. Mirrors
    apps.content.views.NoteOwnershipMixin."""

    def get_object(self, public_id):
        if public_id is None:
            return None
        document = get_object_or_404(
            Note.objects.alive().filter(kind__in=DOCUMENT_KINDS), public_id=public_id,
        )
        if document.owner_id != self.request.user.id:
            raise PermissionDenied
        return document


class DocumentFormView(LoginRequiredMixin, DocumentOwnershipMixin, View):
    template_name = "documents/form.html"

    def get(self, request, public_id=None):
        document = self.get_object(public_id)
        form = DocumentForm(instance=document, owner=request.user)
        return render(request, self.template_name, {"form": form, "document": document})

    def post(self, request, public_id=None):
        document = self.get_object(public_id)
        form = DocumentForm(request.POST, request.FILES, instance=document, owner=request.user)
        if not form.is_valid():
            return render(request, self.template_name, {"form": form, "document": document})

        new_document = form.save(commit=False)
        if document is None:
            new_document.owner = request.user
            new_document = Note.objects.add_root(instance=new_document)
        else:
            new_document.save()
        form.save_m2m()

        remove_ids = [a.pk for a in form.cleaned_data.get("remove_attachments") or []]
        if remove_ids:
            new_document.attachments.alive().filter(pk__in=remove_ids).soft_delete()

        for uploaded_file in form.cleaned_data.get("attachments") or []:
            new_document.attachments.create(
                owner=request.user, file=uploaded_file, visibility=new_document.visibility,
            )

        return redirect("documents:detail", public_id=new_document.public_id)


class DocumentDeleteView(LoginRequiredMixin, DocumentOwnershipMixin, View):
    template_name = "documents/document_confirm_delete.html"

    def get(self, request, public_id):
        document = self.get_object(public_id)
        return render(request, self.template_name, {"document": document})

    def post(self, request, public_id):
        document = self.get_object(public_id)
        document.soft_delete()
        return redirect("documents:list")
