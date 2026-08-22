from django import forms
from django.contrib import admin
from django_ckeditor_5.widgets import CKEditor5Widget
from treebeard.admin import TreeAdmin
from treebeard.forms import MoveNodeForm, movenodeform_factory

from apps.attachments.admin import AttachmentInline
from apps.comments.admin import CommentInline
from apps.common.admin import SoftDeleteAdminMixin, TrashedFilter
from apps.common.enums import ContentFormat
from apps.sharing.admin import ShareLinkInline

from .models import Note


class NoteBaseForm(MoveNodeForm):
    """Swaps the `body` widget by `body_format`: CKEditor5 for HTML, a plain
    monospace textarea for markdown/plaintext (a WYSIWYG editor would mangle
    markdown source). The swap is decided at render time, so switching the
    format takes effect after the next save+reload, not live in the browser.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        body_format = getattr(self.instance, "body_format", None) or ContentFormat.HTML
        if body_format == ContentFormat.HTML:
            self.fields["body"].widget = CKEditor5Widget(config_name="content_note")
        else:
            self.fields["body"].widget = forms.Textarea(attrs={"rows": 20, "style": "font-family: monospace;"})


NoteForm = movenodeform_factory(Note, form=NoteBaseForm)


@admin.register(Note)
class NoteAdmin(SoftDeleteAdminMixin, TreeAdmin):
    form = NoteForm
    inlines = [AttachmentInline, CommentInline, ShareLinkInline]
    list_display = ("title", "kind", "owner", "visibility", "expires_at", "created_at")
    list_filter = (TrashedFilter, "kind", "visibility")
    readonly_fields = ("public_id", "path", "depth", "numchild", "created_at", "updated_at")
    search_fields = ("title", "body")
