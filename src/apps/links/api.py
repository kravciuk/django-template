from django.db.models import Max
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Link, LinkGroup
from .serializers import LinkGroupSerializer, LinkSerializer
from .services import fetch_favicon


def _next_order(queryset):
    return (queryset.aggregate(max_order=Max("order"))["max_order"] or 0) + 1


def _apply_order(model, objects_by_id, ordered_ids):
    """Assign each object's `order` to its index in `ordered_ids` and persist
    in one query. Callers are expected to have already validated that
    `objects_by_id` contains exactly the ids in `ordered_ids`."""
    to_update = []
    for index, object_id in enumerate(ordered_ids):
        obj = objects_by_id[object_id]
        obj.order = index
        to_update.append(obj)
    model.objects.bulk_update(to_update, ["order"])


class LinkGroupViewSet(viewsets.ModelViewSet):
    serializer_class = LinkGroupSerializer

    def get_queryset(self):
        return LinkGroup.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        order = _next_order(LinkGroup.objects.filter(owner=self.request.user))
        serializer.save(owner=self.request.user, order=order)

    @action(detail=False, methods=["post"])
    def reorder(self, request):
        ordered_ids = request.data.get("order") or []
        if not ordered_ids or len(set(ordered_ids)) != len(ordered_ids):
            return Response({"detail": "Invalid group list."}, status=status.HTTP_400_BAD_REQUEST)
        groups_by_id = {group.id: group for group in self.get_queryset().filter(id__in=ordered_ids)}
        if len(groups_by_id) != len(ordered_ids):
            return Response({"detail": "Invalid group list."}, status=status.HTTP_400_BAD_REQUEST)
        _apply_order(LinkGroup, groups_by_id, ordered_ids)
        return Response(status=status.HTTP_204_NO_CONTENT)


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

    @action(detail=False, methods=["post"])
    def reorder(self, request):
        group_id = request.data.get("group")
        ordered_ids = request.data.get("order") or []
        if not ordered_ids or len(set(ordered_ids)) != len(ordered_ids):
            return Response({"detail": "Invalid link list."}, status=status.HTTP_400_BAD_REQUEST)
        links_by_id = {
            link.id: link for link in self.get_queryset().filter(group_id=group_id, id__in=ordered_ids)
        }
        if len(links_by_id) != len(ordered_ids):
            return Response({"detail": "Invalid link list."}, status=status.HTTP_400_BAD_REQUEST)
        _apply_order(Link, links_by_id, ordered_ids)
        return Response(status=status.HTTP_204_NO_CONTENT)
