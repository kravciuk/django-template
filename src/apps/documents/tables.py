import django_tables2 as tables
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html_join
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _

from apps.content.models import Note


class DocumentTable(tables.Table):
    title = tables.Column(
        linkify=dict(viewname="documents:detail", kwargs={"public_id": tables.A("public_id")}),
        verbose_name=_("Title"),
    )
    kind = tables.Column(verbose_name=_("Kind"))
    tags = tables.Column(empty_values=(), orderable=False, verbose_name=_("Tags"))
    expires_at = tables.DateTimeColumn(verbose_name=_("Expires at"))
    status = tables.Column(empty_values=(), orderable=False, verbose_name=_("Status"))
    attachments_count = tables.Column(empty_values=(), orderable=False, verbose_name=_("Files"))

    class Meta:
        model = Note
        fields = ("title", "kind", "tags", "expires_at", "status", "attachments_count")
        # Default: soonest-expiring document first.
        order_by = ("expires_at",)

    def render_tags(self, record):
        # Each tag links back to this same list, pre-filtered to it - same
        # query param the tag-filter form (DocumentFilter.tags) reads.
        list_url = reverse("documents:list")
        return format_html_join(
            ", ",
            '<a href="{}">{}</a>',
            (
                (f"{list_url}?{urlencode({'tags': tag.name})}", tag.name)
                for tag in record.tags.all()
            ),
        )

    def render_status(self, record):
        if record.expires_at is None:
            return _("No expiry")
        if record.expires_at < timezone.now():
            return _("Expired")
        return _("Active")

    def render_attachments_count(self, record):
        return record.attachments.alive().count()
