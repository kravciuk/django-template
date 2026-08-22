import uuid
from pathlib import Path

from django.utils import timezone


def attachment_upload_to(instance, filename):
    """Builds a storage path that never leaks the user-supplied filename -
    avoids path traversal, unicode/length issues, and collisions. The
    original name is preserved separately in Attachment.original_name.
    """
    ext = Path(filename).suffix.lower()
    now = timezone.now()
    owner_id = instance.owner_id or "unowned"
    return f"attachments/{owner_id}/{now:%Y}/{now:%m}/{uuid.uuid4().hex}{ext}"
