from django.db import models


class Visibility(models.TextChoices):
    PUBLIC = "public", "Visible to everyone"
    UNLISTED = "unlisted", "Hidden, reachable via its own direct link"
    SHARED = "shared", "Hidden, reachable only via a generated share link"
    PRIVATE = "private", "Owner only"


class ContentFormat(models.TextChoices):
    HTML = "html", "HTML"
    MARKDOWN = "markdown", "Markdown"
    PLAIN = "plain", "Plain text"
