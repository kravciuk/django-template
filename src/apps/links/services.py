import logging
import uuid
from io import BytesIO
from urllib.parse import urlparse

import requests
from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger("apps")

FAVICON_TIMEOUT = 5
FAVICON_MAX_BYTES = 300 * 1024

# PIL's format names don't always match a conventional file extension
# (e.g. ICO's own MIME type is "image/x-icon") - map the ones favicon.ico
# realistically comes back as explicitly rather than deriving from Image.MIME.
FORMAT_EXTENSIONS = {
    "ICO": "ico",
    "PNG": "png",
    "GIF": "gif",
    "JPEG": "jpg",
    "BMP": "bmp",
    "WEBP": "webp",
    "SVG": "svg",
}


def fetch_favicon(url):
    """Best-effort fetch of `https://<domain>/favicon.ico` for a freshly
    added Link. Returns a (ContentFile, filename) tuple on success, or None
    on any failure - a missing/broken favicon must never block saving the
    link itself, so every error path here just logs and returns None.
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return None
    favicon_url = f"{parsed.scheme}://{parsed.netloc}/favicon.ico"

    try:
        response = requests.get(favicon_url, timeout=FAVICON_TIMEOUT, stream=True)
    except requests.RequestException as exc:
        logger.info("fetch_favicon: request to %s failed: %s", favicon_url, exc)
        return None

    with response:
        if response.status_code != 200:
            return None
        content_type = response.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            return None

        data = BytesIO()
        size = 0
        for chunk in response.iter_content(chunk_size=8192):
            size += len(chunk)
            if size > FAVICON_MAX_BYTES:
                logger.info("fetch_favicon: %s exceeded size cap, skipping", favicon_url)
                return None
            data.write(chunk)

    data.seek(0)
    try:
        image = Image.open(data)
        image.verify()  # cheap guard against an HTML error page served as image/*
    except (UnidentifiedImageError, OSError) as exc:
        logger.info("fetch_favicon: %s is not a valid image: %s", favicon_url, exc)
        return None

    ext = FORMAT_EXTENSIONS.get(image.format, "ico")
    filename = f"{uuid.uuid4().hex}.{ext}"
    return ContentFile(data.getvalue(), name=filename)
