from django.contrib import admin


class TrashedFilter(admin.SimpleListFilter):
    """Active / Trashed / All filter for any SoftDeleteModel admin.

    Defaults to "Active" - the manager itself doesn't filter (see
    SoftDeleteManager's docstring), so without this the changelist would
    show trashed rows mixed in by default.
    """

    title = "trash status"
    parameter_name = "trashed"

    def lookups(self, request, model_admin):
        return [("active", "Active"), ("trashed", "Trashed"), ("all", "All")]

    def value(self):
        return super().value() or "active"

    def queryset(self, request, queryset):
        value = self.value()
        if value == "trashed":
            return queryset.trashed()
        if value == "all":
            return queryset
        return queryset.alive()


class SoftDeleteAdminMixin:
    """Adds the Active/Trashed/All filter and trash-related bulk actions.

    Mix into any ModelAdmin for a SoftDeleteModel:
        class FooAdmin(SoftDeleteAdminMixin, admin.ModelAdmin): ...
    """

    list_filter = (TrashedFilter,)
    actions = ["soft_delete_selected", "restore_selected", "purge_selected"]

    @admin.action(description="Move selected to trash")
    def soft_delete_selected(self, request, queryset):
        count = queryset.count()
        queryset.soft_delete()
        self.message_user(request, f"Moved {count} item(s) to trash.")

    @admin.action(description="Restore selected from trash")
    def restore_selected(self, request, queryset):
        count = queryset.count()
        queryset.restore()
        self.message_user(request, f"Restored {count} item(s) from trash.")

    @admin.action(description="Permanently delete selected (bypasses trash)")
    def purge_selected(self, request, queryset):
        # Deliberately a plain queryset.delete(), unlike the purge_trash
        # command's extra subtree-safety check for Note (see
        # apps.content.services) - this is an explicit "delete this now"
        # click, where cascading to descendants is exactly what's expected.
        count = queryset.count()
        queryset.delete()
        self.message_user(request, f"Permanently deleted {count} item(s).", level="warning")
