from django.apps import AppConfig


class AttachmentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.attachments"
    label = "attachments"

    def ready(self):
        from . import signals  # noqa: F401

        # Pillow can't decode HEIC/HEIF natively (the format iPhones save
        # photos in by default) - registering this plugin lets both
        # metadata extraction (models.py) and thumbnail generation
        # (imagekit) open them like any other image.
        import pillow_heif

        pillow_heif.register_heif_opener()
