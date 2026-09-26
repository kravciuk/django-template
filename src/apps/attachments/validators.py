from constance import config
from django.core.exceptions import ValidationError

DEFAULT_MAX_UPLOAD_SIZE = 25 * 1024 * 1024  # 25 MB
DEFAULT_ALLOWED_EXTENSIONS = ""  # empty = no restriction


def validate_upload_size(value):
    max_size = getattr(config, "ATTACHMENTS_MAX_UPLOAD_SIZE", DEFAULT_MAX_UPLOAD_SIZE)
    if max_size and value.size > max_size:
        raise ValidationError(f"File is too large ({value.size} bytes); the limit is {max_size} bytes.")


def validate_upload_extension(value):
    allowed = getattr(config, "ATTACHMENTS_ALLOWED_EXTENSIONS", DEFAULT_ALLOWED_EXTENSIONS)
    allowed = [e.strip() for e in allowed.split(",") if e.strip()]
    if not allowed:
        return
    ext = value.name.rsplit(".", 1)[-1].lower() if "." in value.name else ""
    if ext not in {e.lower().lstrip(".") for e in allowed}:
        raise ValidationError(f"Files with extension '.{ext}' are not allowed.")
