from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views import View

from apps.sharing.access import can_view

from .models import Attachment


class AttachmentDownloadView(View):
    """Serves the file with its original filename and a
    Content-Disposition: attachment header.

    The file itself is stored under an unguessable, randomized path (see
    apps.attachments.utils.attachment_upload_to) that never carries the
    original filename, so a bare link to `Attachment.file.url` downloads
    with a meaningless name. This view looks the original name back up
    from the database instead.
    """

    def get(self, request, public_id):
        attachment = get_object_or_404(Attachment.objects.alive(), public_id=public_id)
        if not can_view(attachment, request.user):
            raise Http404
        filename = attachment.original_name or attachment.file.name.rsplit("/", 1)[-1]
        return FileResponse(attachment.file.open("rb"), as_attachment=True, filename=filename)
