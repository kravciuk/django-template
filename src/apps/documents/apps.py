from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    """Web UI (views/forms/tables/filters/templates) for "documents" -
    contracts, receipts, warranties with an expiration date. Stores nothing
    of its own: a document is an apps.content.Note whose `kind` is one of
    DOCUMENT_KINDS (see enums.py), with files attached the same way any
    Note attaches an apps.attachments.Attachment. No models, no migrations.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.documents"
    label = "documents"
