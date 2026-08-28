"""Builds `home_data` - the JSON payload embedded via `json_script` in
content/home.html and rendered by the React `HomeContent` island. Reuses
HomeView.get_queryset()'s own `entries` for the note cards (no extra query),
and mirrors apps.documents' existing "recently added" / "expiring within N
days" logic for the documents column (see apps.documents.views.
DocumentListView.get_queryset / apps.documents.filters.DocumentFilter.
filter_expires_within_days) rather than reimplementing it differently.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.content.enums import NoteKind
from apps.content.models import Note
from apps.documents.enums import DOCUMENT_KINDS

RECENT_DOCUMENTS_LIMIT = 5
EXPIRING_DOCUMENTS_LIMIT = 5
EXPIRING_WITHIN_DAYS = 30

_MONTHS_SHORT = {
    1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "май", 6: "июн",
    7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек",
}
_MONTHS_GENITIVE = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


def _short_date(value):
    """"28 авг 2026" - the note-card date format."""
    return f"{value.day} {_MONTHS_SHORT[value.month]} {value.year}"


def _short_date_no_year(value):
    """"25 авг" - the "recently added documents" row format."""
    return f"{value.day} {_MONTHS_SHORT[value.month]}"


def _genitive_date(value):
    """"5 сентября 2026" - the "expires" wording ("до {genitive_date}")."""
    return f"{value.day} {_MONTHS_GENITIVE[value.month]} {value.year}"


def _kind_label(kind):
    return {
        NoteKind.NOTE: _("Заметка"),
        NoteKind.ALBUM: _("Альбом"),
        NoteKind.PURCHASE: _("Покупка"),
        NoteKind.WARRANTY: _("Гарантия"),
        NoteKind.CONTRACT: _("Договор"),
        NoteKind.REMINDER: _("Напоминание"),
    }.get(kind, kind)


def _note_card(entry):
    note = entry["note"]
    cover = entry["cover"]
    return {
        "public_id": str(note.public_id),
        "title": note.title,
        "kind_label": _kind_label(note.kind),
        "created_at_display": _short_date(timezone.localtime(note.created_at)),
        "excerpt": entry["excerpt"],
        "has_cover": cover is not None,
        "cover_url": cover.file.url if cover else None,
        "detail_url": reverse("content:note_detail", args=[note.public_id]),
    }


def _recent_document(note):
    return {
        "title": note.title,
        "date_display": _short_date_no_year(timezone.localtime(note.created_at)),
        "detail_url": reverse("documents:detail", args=[note.public_id]),
    }


def _expiring_document(note):
    today = timezone.localtime().date()
    return {
        "title": note.title,
        "expires_at_display": _genitive_date(timezone.localtime(note.expires_at)),
        "days_left": (note.expires_at.date() - today).days,
        "detail_url": reverse("documents:detail", args=[note.public_id]),
    }


def _build_documents_block(request):
    # Documents are always per-owner (see DocumentListView) - the home page
    # itself stays public, it just doesn't show anyone's documents until
    # they're signed in, rather than becoming a login wall.
    if not request.user.is_authenticated:
        return None

    documents = Note.objects.alive().filter(kind__in=DOCUMENT_KINDS, owner=request.user)

    recent = documents.order_by("-created_at")[:RECENT_DOCUMENTS_LIMIT]

    now = timezone.now()
    expiring = documents.filter(
        expires_at__gte=now, expires_at__lte=now + timedelta(days=EXPIRING_WITHIN_DAYS),
    ).order_by("expires_at")[:EXPIRING_DOCUMENTS_LIMIT]

    return {
        "recent": [_recent_document(note) for note in recent],
        "expiring": [_expiring_document(note) for note in expiring],
    }


def build_home_payload(request, entries):
    """JSON-serializable payload for the home page's React island."""
    return {
        "notes": [_note_card(entry) for entry in entries],
        "documents": _build_documents_block(request),
    }
