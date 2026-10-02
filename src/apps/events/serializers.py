from datetime import datetime, time

from django.core.exceptions import ValidationError as DjangoValidationError
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.common.enums import ContentFormat
from apps.content.models import Note

from .recurrence import all_day_date, all_day_moment, validate_rrule
from .services import from_api_end, to_api_end, to_api_start


class CalendarMomentField(serializers.Field):
    """Accepts either a date ("2026-10-05", what FullCalendar sends for
    all-day selections) or an ISO datetime (naive = the active time zone).
    The serializer's validate() turns it into the stored representation."""

    def to_internal_value(self, data):
        if data in (None, ""):
            return None
        if isinstance(data, str):
            value = parse_date(data) if len(data) == 10 else parse_datetime(data)
            if value is not None:
                if isinstance(value, datetime) and timezone.is_naive(value):
                    value = timezone.make_aware(value)
                return value
        raise serializers.ValidationError(_("Enter a valid date or date/time."))

    def to_representation(self, value):
        return value


def _as_all_day(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return timezone.localtime(value).date()
    return value


def _as_moment(value):
    if value is None or isinstance(value, datetime):
        return value
    return timezone.make_aware(datetime.combine(value, time.min))


class QuickNoteSerializer(serializers.ModelSerializer):
    """The /events/ modal's (and drag/resize's) view of a Note.

    `starts_at`/`ends_at` use the wire conventions FullCalendar and Google
    share: for all-day notes they are dates and `ends_at` is *exclusive*;
    it's stored as an inclusive last day in Note.expires_at (see
    services.to_api_end/from_api_end).
    """

    starts_at = CalendarMomentField(required=False, allow_null=True)
    ends_at = CalendarMomentField(required=False, allow_null=True)
    is_draft = serializers.BooleanField(write_only=True, required=False, default=False)
    edit_url = serializers.SerializerMethodField()
    detail_url = serializers.SerializerMethodField()

    class Meta:
        model = Note
        fields = [
            "public_id", "title", "body", "body_format", "kind", "starts_at", "ends_at", "all_day",
            "color", "recurrence", "remind_minutes_before", "is_draft", "edit_url", "detail_url",
        ]
        read_only_fields = ["public_id", "body_format", "kind"]
        extra_kwargs = {"body": {"required": False, "allow_blank": True}}

    def get_edit_url(self, note):
        return reverse("content:note_edit", args=[note.public_id])

    def get_detail_url(self, note):
        return reverse("content:note_detail", args=[note.public_id])

    def validate_recurrence(self, value):
        try:
            validate_rrule(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return value

    def validate(self, attrs):
        instance = self.instance
        all_day = attrs.get("all_day", instance.all_day if instance else False)

        # Effective start/end on the wire for whichever of them wasn't sent
        # (a PATCH from drag/resize may send only one).
        if "starts_at" in attrs:
            start = attrs.pop("starts_at")
        else:
            start = instance.starts_at if instance else None
            if instance is not None and instance.all_day and start is not None:
                start = all_day_date(start)
        if "ends_at" in attrs:
            end = attrs.pop("ends_at")
            end_is_wire = True
        else:
            end = instance.expires_at if instance else None
            end_is_wire = False
            if instance is not None and instance.all_day and end is not None:
                end = all_day_date(end)

        if all_day:
            start_day, end_day = _as_all_day(start), _as_all_day(end)
            if end_day is not None and end_is_wire:
                end_day = from_api_end(end_day)
            if start_day is not None and end_day is not None and end_day < start_day:
                raise serializers.ValidationError({"ends_at": _("The end can't be before the start.")})
            attrs["starts_at"] = all_day_moment(start_day) if start_day else None
            attrs["expires_at"] = all_day_moment(end_day) if end_day else None
        else:
            start_at, end_at = _as_moment(start), _as_moment(end)
            if start_at is not None and end_at is not None and end_at < start_at:
                raise serializers.ValidationError({"ends_at": _("The end can't be before the start.")})
            attrs["starts_at"], attrs["expires_at"] = start_at, end_at

        if attrs["starts_at"] is None and attrs["expires_at"] is None:
            raise serializers.ValidationError({"starts_at": _("Set a start or an end date.")})

        # Rich-text (HTML/Markdown) bodies are edited in the full form only -
        # the modal's plain textarea would mangle them.
        if instance is not None and instance.body_format != ContentFormat.PLAIN:
            attrs.pop("body", None)
        # Only a brand-new quick note can be born as a draft ("Open full form").
        if instance is not None:
            attrs.pop("is_draft", None)
        return attrs

    def to_representation(self, note):
        data = super().to_representation(note)
        data["starts_at"] = to_api_start(note, note.starts_at)
        data["ends_at"] = to_api_end(note, note.expires_at)
        return data
