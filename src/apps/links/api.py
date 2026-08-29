from django.db.models import Max
from rest_framework import viewsets

from .models import Link, LinkGroup
from .serializers import LinkGroupSerializer, LinkSerializer
from .services import fetch_favicon


def _next_order(queryset):
    return (queryset.aggregate(max_order=Max("order"))["max_order"] or 0) + 1


class LinkGroupViewSet(viewsets.ModelViewSet):
    serializer_class = LinkGroupSerializer

    def get_queryset(self):
        return LinkGroup.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        order = _next_order(LinkGroup.objects.filter(owner=self.request.user))
        serializer.save(owner=self.request.user, order=order)


class LinkViewSet(viewsets.ModelViewSet):
    serializer_class = LinkSerializer

    def get_queryset(self):
        return Link.objects.filter(group__owner=self.request.user)

    def perform_create(self, serializer):
        group = serializer.validated_data["group"]
        order = _next_order(Link.objects.filter(group=group))
        link = serializer.save(author=self.request.user, order=order)

        favicon = fetch_favicon(link.url)
        if favicon is not None:
            link.favicon.save(favicon.name, favicon, save=True)

    def perform_update(self, serializer):
        old_url = serializer.instance.url
        link = serializer.save()

        # Only re-fetch when the URL actually changed - and only replace the
        # favicon on success, so a transient fetch failure never wipes out a
        # perfectly good icon the link already had.
        if link.url != old_url:
            favicon = fetch_favicon(link.url)
            if favicon is not None:
                link.favicon.save(favicon.name, favicon, save=True)
