from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline

from apps.common.admin import SoftDeleteAdminMixin, TrashedFilter
from libs.utils import get_client_ip

from .models import Comment


class CommentInline(GenericTabularInline):
    """Reusable inline - included by NoteAdmin and AttachmentAdmin."""

    model = Comment
    ct_field = "content_type"
    ct_fk_field = "object_id"
    extra = 0
    fields = ("owner", "parent", "body", "ip", "created_at", "edited_at", "deleted_at")
    readonly_fields = ("ip", "created_at", "edited_at")
    show_change_link = True


@admin.register(Comment)
class CommentAdmin(SoftDeleteAdminMixin, admin.ModelAdmin):
    list_display = ("id", "owner", "content_type", "object_id", "depth", "created_at", "is_trashed")
    list_filter = (TrashedFilter, "content_type")
    readonly_fields = ("ip", "depth", "created_at", "edited_at")
    search_fields = ("body",)

    @admin.display(boolean=True, description="Trashed")
    def is_trashed(self, obj):
        return obj.is_trashed

    def save_model(self, request, obj, form, change):
        if not obj.owner_id:
            obj.owner = request.user
        if not change:
            obj.ip = get_client_ip(request)
        super().save_model(request, obj, form, change)
