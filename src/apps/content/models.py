from django.contrib.contenttypes.fields import GenericRelation
from django.core.validators import RegexValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from taggit.managers import TaggableManager
from treebeard.mp_tree import MP_Node

from apps.attachments.models import Attachment
from apps.comments.mixins import CommentableMixin
from apps.common.enums import ContentFormat, Visibility
from apps.common.models import ExpiryModel, OwnedModel, SoftDeleteModel, TimeStampedModel, VisibilityModel
from apps.sharing.mixins import ShareableMixin

from .enums import NoteKind
from .managers import NoteManager


class Note(
    MP_Node, TimeStampedModel, OwnedModel, VisibilityModel, SoftDeleteModel, ExpiryModel,
    CommentableMixin, ShareableMixin,
):
    """The universal container from the spec: a plain note, a photo album,
    a purchase record with a warranty date, a chord sheet - all the same
    table, told apart by `kind`. Forms an unlimited-depth tree via
    treebeard's Materialized Path (see NoteManager/NoteQuerySet for why the
    manager needs a get_queryset() override).

    There is no separate Album model: "a group of photos with a caption" is
    just a Note (kind=ALBUM) with ordered Attachments (Attachment.position /
    is_cover) - the note tree already gives albums a free hierarchy.
    """

    title = models.CharField(max_length=255)
    kind = models.CharField(max_length=16, choices=NoteKind.choices, default=NoteKind.NOTE, db_index=True)
    body_format = models.CharField(max_length=16, choices=ContentFormat.choices, default=ContentFormat.HTML)
    body = models.TextField(blank=True)
    json_data = models.JSONField(default=dict, blank=True)
    # True from the moment autosave first creates this row until the user
    # explicitly clicks "Save" - see apps/content/views.py::NoteFormView/
    # NoteAutosaveView. A draft is owner-only regardless of `visibility`
    # (apps/sharing/access.py::can_view) and excluded from public listings.
    is_draft = models.BooleanField(default=False, db_index=True)

    # Calendar placement (apps.events). A note shows up on /events/ once it
    # has `starts_at` and/or ExpiryModel's `expires_at`, which doubles as
    # the event end here (and stays the deadline for document kinds).
    # All-day events store UTC midnight of each date, with an *inclusive*
    # end day - the exclusive-end convention FullCalendar/Google use is
    # converted only at the API boundary (apps.events.services).
    starts_at = models.DateTimeField(_("Starts at"), null=True, blank=True, db_index=True)
    all_day = models.BooleanField(_("All day"), default=False)
    # Empty = the per-source default from constance (EVENTS_NOTE_COLOR /
    # EVENTS_DOCUMENT_COLOR).
    color = models.CharField(
        _("Calendar color"), max_length=7, blank=True,
        validators=[RegexValidator(r"^#[0-9a-fA-F]{6}$", _("Enter a color as #rrggbb."))],
    )
    # An RFC 5545 RRULE body without DTSTART (e.g. "FREQ=YEARLY"); the
    # series starts at starts_at (or expires_at if there's no start). See
    # apps.events.recurrence.
    recurrence = models.CharField(_("Repeat"), max_length=255, blank=True)
    # Relative, so it keeps working across every occurrence of a recurring
    # event. ExpiryModel.remind_at holds the resulting *next* fire time,
    # recomputed on every save - see apps.events.reminders.
    remind_minutes_before = models.PositiveIntegerField(_("Remind before (minutes)"), null=True, blank=True)

    attachments = GenericRelation(
        Attachment, content_type_field="content_type", object_id_field="object_id",
    )
    tags = TaggableManager(blank=True)

    objects = NoteManager()

    class Meta:
        # treebeard traverses the tree by `path` - any other default
        # ordering (e.g. -created_at) breaks that.
        ordering = ["path"]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # A Node is a hidden hub: force it, regardless of what was
        # requested (public form, unrestricted admin form, autosave, or a
        # shell/script), so it can never end up PUBLIC and listed - see
        # HomeView.get_queryset filtering on visibility=PUBLIC.
        if self.kind == NoteKind.NODE:
            self.visibility = Visibility.UNLISTED
        if self.body_format == ContentFormat.HTML and self.body:
            from libs.html import sanitize_html

            self.body = sanitize_html(self.body)
        super().save(*args, **kwargs)

    def soft_delete(self):
        # Overrides SoftDeleteModel.soft_delete(): trashing a note must
        # cascade to its subtree, attachments and comments as one atomic,
        # same-timestamp operation - see apps.content.services.
        from .services import soft_delete_note

        return soft_delete_note(self)

    def restore(self):
        from .services import restore_note

        return restore_note(self)

    @classmethod
    def purge_stale(cls, cutoff, dry_run=False):
        from .services import purge_stale_notes

        return purge_stale_notes(cutoff, dry_run=dry_run)
