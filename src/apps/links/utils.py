import uuid
from pathlib import Path


def link_favicon_upload_to(instance, filename):
    """Builds a storage path that never leaks the fetched filename - avoids
    path traversal, unicode/length issues, and collisions across users. Same
    approach as apps.attachments.utils.attachment_upload_to.
    """
    ext = Path(filename).suffix.lower()
    owner_id = instance.group.owner_id if instance.group_id else "unowned"
    return f"links/favicons/{owner_id}/{uuid.uuid4().hex}{ext}"
