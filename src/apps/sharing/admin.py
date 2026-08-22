from django import forms
from django.contrib import admin
from django.contrib.contenttypes.admin import GenericTabularInline

from .models import ShareLink


class ShareLinkForm(forms.ModelForm):
    """The hashed `password` column is never editable directly - this
    write-only field goes through ShareLink.set_password() instead."""

    raw_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput,
        label="Password",
        help_text="Leave blank for no password, or to keep the current one when editing.",
    )

    class Meta:
        model = ShareLink
        exclude = ("password",)

    def save(self, commit=True):
        instance = super().save(commit=False)
        raw_password = self.cleaned_data.get("raw_password")
        if raw_password:
            instance.set_password(raw_password)
        if commit:
            instance.save()
        return instance


class ShareLinkInline(GenericTabularInline):
    """Reusable inline - included by NoteAdmin and AttachmentAdmin."""

    model = ShareLink
    form = ShareLinkForm
    ct_field = "content_type"
    ct_fk_field = "object_id"
    extra = 0
    fields = ("token", "raw_password", "is_active", "expires_at", "max_uses", "used_count", "comment")
    readonly_fields = ("token", "used_count")
    show_change_link = True


@admin.register(ShareLink)
class ShareLinkAdmin(admin.ModelAdmin):
    form = ShareLinkForm
    list_display = ("token", "owner", "content_type", "object_id", "is_active", "expires_at", "used_count")
    list_filter = ("is_active", "content_type")
    readonly_fields = ("token", "used_count", "last_used_at", "created_at", "updated_at")
    search_fields = ("token", "comment")
