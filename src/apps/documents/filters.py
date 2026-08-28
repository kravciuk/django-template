from datetime import timedelta

import django_filters
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.content.models import Note

STATUS_EXPIRED = "expired"
STATUS_ACTIVE = "active"


class DocumentFilter(django_filters.FilterSet):
    status = django_filters.ChoiceFilter(
        label=_("Status"),
        choices=[(STATUS_EXPIRED, _("Expired")), (STATUS_ACTIVE, _("Active"))],
        method="filter_status",
        empty_label=_("Any"),
    )
    # Renders as two date inputs (expires_range_0/expires_range_1) - covers
    # "expires between {date from}-{date to}".
    expires_range = django_filters.DateFromToRangeFilter(
        field_name="expires_at", label=_("Expires between"),
    )
    # "expires within the next X days".
    expires_within_days = django_filters.NumberFilter(
        label=_("Expires within (days)"), method="filter_expires_within_days",
    )
    # Rendered by the same chips + autocomplete widget as NoteForm.tags
    # (apps/content/static/content/js/tag_autocomplete.js, keyed off this
    # field's id="id_tags") - so the submitted value is a comma-separated
    # list of exact tag names, not a single substring.
    tags = django_filters.CharFilter(label=_("Tag"), method="filter_tags")

    class Meta:
        model = Note
        fields = []  # every filter above is either a method filter or an explicit field_name

    def filter_tags(self, queryset, name, value):
        tag_names = [tag.strip() for tag in value.split(",") if tag.strip()]
        if not tag_names:
            return queryset
        return queryset.filter(tags__name__in=tag_names).distinct()

    def filter_status(self, queryset, name, value):
        now = timezone.now()
        if value == STATUS_EXPIRED:
            return queryset.filter(expires_at__lt=now)
        if value == STATUS_ACTIVE:
            # "Active" also covers documents with no expiry set at all.
            return queryset.filter(Q(expires_at__gte=now) | Q(expires_at__isnull=True))
        return queryset

    def filter_expires_within_days(self, queryset, name, value):
        if value is None:
            return queryset
        now = timezone.now()
        return queryset.filter(expires_at__gte=now, expires_at__lte=now + timedelta(days=value))
