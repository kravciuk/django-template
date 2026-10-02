from datetime import datetime

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext as _
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.enums import ContentFormat, Visibility
from apps.content.enums import NoteKind
from apps.content.models import Note
from apps.documents.enums import DOCUMENT_KINDS

from .serializers import QuickNoteSerializer
from .services import SOURCES, calendar_entries, calendar_tags, get_events_hub


def _parse_bound(value):
    """A FullCalendar range bound: an ISO date/datetime, naive ones in the
    active (user) time zone."""
    if not value:
        return None
    parsed = parse_datetime(value)
    if parsed is None:
        day = parse_date(value[:10])
        if day is None:
            return None
        parsed = datetime.combine(day, datetime.min.time())
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


def _split(value):
    return [item for item in (value or "").split(",") if item]


class CalendarFeedView(APIView):
    """GET ?start=&end=[&sources=note,document][&tags=a,b] - the FullCalendar
    event source for /events/ (and anything else that wants the same data)."""

    def get(self, request):
        start = _parse_bound(request.query_params.get("start"))
        end = _parse_bound(request.query_params.get("end"))
        if start is None or end is None or end <= start:
            return Response({"detail": _("Invalid date range.")}, status=status.HTTP_400_BAD_REQUEST)
        sources = [source for source in _split(request.query_params.get("sources")) if source in SOURCES]
        if "sources" in request.query_params and not sources:
            return Response([])
        entries = calendar_entries(
            request.user, start, end,
            sources=sources or None,
            tags=_split(request.query_params.get("tags")) or None,
        )
        return Response(entries)


class CalendarTagsView(APIView):
    def get(self, request):
        return Response(calendar_tags(request.user))


class QuickNoteViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Create/read/update/trash calendar notes from the /events/ modal and
    drag/resize. Documents and hub nodes are out of reach on purpose -
    documents are edited on their own pages."""

    serializer_class = QuickNoteSerializer
    lookup_field = "public_id"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        return (
            Note.objects.alive()
            .filter(owner=self.request.user)
            .exclude(kind__in=[*DOCUMENT_KINDS, NoteKind.NODE])
        )

    def perform_create(self, serializer):
        note = Note(
            owner=self.request.user,
            kind=NoteKind.EVENT,
            body_format=ContentFormat.PLAIN,
            visibility=Visibility.PRIVATE,
            **serializer.validated_data,
        )
        serializer.instance = Note.objects.add_child(get_events_hub(self.request.user), instance=note)

    def perform_destroy(self, instance):
        instance.soft_delete()
