from django.db import models


class AttachmentKind(models.TextChoices):
    IMAGE = "image", "Image"
    DOCUMENT = "document", "Document"
    AUDIO = "audio", "Audio"
    VIDEO = "video", "Video"
    OTHER = "other", "Other"
