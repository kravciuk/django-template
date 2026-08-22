from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline
from django.utils.html import format_html

from apps.common.admin import SoftDeleteAdminMixin, TrashedFilter

from .enums import AttachmentKind
from .models import Attachment


class AttachmentInline(GenericTabularInline):
    """Reusable inline - included by NoteAdmin."""

    model = Attachment
    ct_field = "content_type"
    ct_fk_field = "object_id"
    extra = 0
    fields = ("file", "position", "is_cover", "kind", "title", "preview")
    readonly_fields = ("kind", "preview")
    show_change_link = True

    @admin.display(description="Preview")
    def preview(self, obj):
        if obj.pk and obj.kind == AttachmentKind.IMAGE and obj.file:
            return format_html('<img src="{}" style="max-height:60px" />', obj.file.url)
        return "-"


@admin.register(Attachment)
class AttachmentAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("id", "display_name", "kind", "owner", "content_type", "object_id", "size", "created_at")
    list_filter = (TrashedFilter, "kind", "content_type")
    readonly_fields = (
        "original_name", "mime_type", "size", "checksum", "width", "height", "created_at", "updated_at",
    )
    search_fields = ("title", "original_name", "description")

    @admin.display(description="Name")
    def display_name(self, obj):
        return obj.title or obj.original_name
