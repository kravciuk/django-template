from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.common.models import OwnedModel, TimeStampedModel

from .utils import link_favicon_upload_to

MIN_CARDS_PER_ROW = 1
MAX_CARDS_PER_ROW = 8


class LinkGroup(OwnedModel, TimeStampedModel):
    """A named block of links on the user's /links/ dashboard (private per
    owner - see OwnedModel). `cards_per_row` drives the CSS grid the links
    are rendered in (see templates/links/home.html)."""

    title = models.CharField(_("title"), max_length=100)
    cards_per_row = models.PositiveSmallIntegerField(
        _("cards per row"),
        default=4,
        validators=[MinValueValidator(MIN_CARDS_PER_ROW), MaxValueValidator(MAX_CARDS_PER_ROW)],
    )
    order = models.PositiveIntegerField(_("order"), default=0, db_index=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = _("link group")
        verbose_name_plural = _("link groups")

    def __str__(self):
        return self.title


class Link(TimeStampedModel):
    """A single bookmarked link inside a LinkGroup. `favicon` is fetched
    automatically on creation (see apps.links.services.fetch_favicon) - it's
    optional since not every site serves a /favicon.ico."""

    group = models.ForeignKey(LinkGroup, related_name="links", on_delete=models.CASCADE, verbose_name=_("group"))
    url = models.URLField(_("URL"), max_length=500)
    title = models.CharField(_("title"), max_length=200)
    favicon = models.ImageField(_("favicon"), upload_to=link_favicon_upload_to, blank=True, null=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="added_links",
        verbose_name=_("author"),
    )
    order = models.PositiveIntegerField(_("order"), default=0, db_index=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = _("link")
        verbose_name_plural = _("links")

    def __str__(self):
        return self.title
