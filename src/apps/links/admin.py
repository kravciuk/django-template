from django.contrib import admin

from .models import Link, LinkGroup


class LinkInline(admin.TabularInline):
    model = Link
    extra = 0
    fields = ("title", "url", "favicon", "author", "order")
    readonly_fields = ("author",)


@admin.register(LinkGroup)
class LinkGroupAdmin(admin.ModelAdmin):
    inlines = [LinkInline]
    list_display = ("title", "owner", "cards_per_row", "order", "created_at")
    list_filter = ("owner",)
    search_fields = ("title",)


@admin.register(Link)
class LinkAdmin(admin.ModelAdmin):
    list_display = ("title", "group", "url", "author", "order", "created_at")
    list_filter = ("group__owner",)
    search_fields = ("title", "url")
    readonly_fields = ("author",)
