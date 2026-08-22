from django.db import models


class NoteKind(models.TextChoices):
    NOTE = "note", "Note"
    ALBUM = "album", "Album"
    PURCHASE = "purchase", "Purchase"
    WARRANTY = "warranty", "Warranty"
    CONTRACT = "contract", "Contract"
    REMINDER = "reminder", "Reminder"
