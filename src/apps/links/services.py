import logging
import uuid
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urljoin, urlparse

import requests
from django.core.files.base import ContentFile
from django.db.models import Q
from PIL import Image, UnidentifiedImageError

from .models import Link

logger = logging.getLogger("apps")

FAVICON_TIMEOUT = 5
FAVICON_MAX_BYTES = 300 * 1024
# Cap on how much of a link's own HTML page is read while looking for
# <link rel="icon"> - the tags live in <head>, so the start of the page is enough.
FAVICON_PAGE_MAX_BYTES = 512 * 1024
FAVICON_MAX_HTML_CANDIDATES = 3
ALLOWED_SCHEMES = ("http", "https")
# Some sites reject the default python-requests User-Agent outright.
FAVICON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
}
# Last-resort source for sites that block server-side requests entirely
# (e.g. Cloudflare bot protection). Answers 404 for a domain it has no icon
# for, so its generic placeholder is rejected by the status check.
GOOGLE_FAVICON_URL = "https://www.google.com/s2/favicons?domain={host}&sz=64"

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


class _IconLinkParser(HTMLParser):
    """Collects hrefs of <link rel="... icon ..."> tags, split into regular
    icons and apple-touch-icons so the former can be preferred."""

    def __init__(self):
        super().__init__()
        self.icons = []
        self.touch_icons = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        attrs = dict(attrs)
        rel = (attrs.get("rel") or "").lower().split()
        href = (attrs.get("href") or "").strip()
        if not href:
            return
        if "icon" in rel:
            self.icons.append(href)
        elif any(token.startswith("apple-touch-icon") for token in rel):
            self.touch_icons.append(href)


def fetch_favicon(url):
    """Best-effort favicon lookup for a Link. Tries, in order:
    `<scheme>://<host>/favicon.ico`, the <link rel="icon"> tags of the
    link's own page, then Google's favicon service. Returns a ContentFile on
    the first success, or None - a missing/broken favicon must never block
    saving the link itself, so every error path here just logs and returns None.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.netloc:
        return None

    favicon = _download_icon(f"{parsed.scheme}://{parsed.netloc}/favicon.ico")
    if favicon is not None:
        return favicon

    for icon_url in _icon_urls_from_html(url):
        favicon = _download_icon(icon_url)
        if favicon is not None:
            return favicon

    if parsed.hostname:
        return _download_icon(GOOGLE_FAVICON_URL.format(host=parsed.hostname))
    return None


def refetch_missing_favicons():
    """Retries fetch_favicon for every Link that still has no favicon.
    Returns (checked, fixed) counts."""
    links = Link.objects.filter(Q(favicon__isnull=True) | Q(favicon="")).select_related("group")
    checked = fixed = 0
    for link in links.iterator():
        checked += 1
        favicon = fetch_favicon(link.url)
        if favicon is not None:
            link.favicon.save(favicon.name, favicon, save=True)
            fixed += 1
    return checked, fixed


def _get(url):
    return requests.get(url, timeout=FAVICON_TIMEOUT, stream=True, headers=FAVICON_HEADERS)


def _read_capped(response, max_bytes):
    """Reads a streamed response body, or returns None once it exceeds max_bytes."""
    data = BytesIO()
    size = 0
    for chunk in response.iter_content(chunk_size=8192):
        size += len(chunk)
        if size > max_bytes:
            return None
        data.write(chunk)
    return data


def _download_icon(icon_url):
    """Downloads and validates a single icon URL; ContentFile or None."""
    try:
        response = _get(icon_url)
    except requests.RequestException as exc:
        logger.info("fetch_favicon: request to %s failed: %s", icon_url, exc)
        return None

    with response:
        if response.status_code != 200:
            return None
        content_type = response.headers.get("Content-Type", "")
        if not content_type.startswith("image/"):
            return None
        data = _read_capped(response, FAVICON_MAX_BYTES)
        if data is None:
            logger.info("fetch_favicon: %s exceeded size cap, skipping", icon_url)
            return None

    data.seek(0)
    try:
        image = Image.open(data)
        image.verify()  # cheap guard against an HTML error page served as image/*
    # PIL reports a corrupt PNG (bad chunk checksum) as SyntaxError.
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        logger.info("fetch_favicon: %s is not a valid image: %s", icon_url, exc)
        return None

    ext = FORMAT_EXTENSIONS.get(image.format, "ico")
    filename = f"{uuid.uuid4().hex}.{ext}"
    return ContentFile(data.getvalue(), name=filename)


def _icon_urls_from_html(page_url):
    """Absolute http(s) icon URLs declared in the page's <link> tags,
    regular icons before apple-touch-icons; empty list on any failure."""
    try:
        response = _get(page_url)
    except requests.RequestException as exc:
        logger.info("fetch_favicon: request to %s failed: %s", page_url, exc)
        return []

    with response:
        if response.status_code != 200:
            return []
        if not response.headers.get("Content-Type", "").startswith("text/html"):
            return []
        # A page larger than the cap is fine - its <head> is in the part
        # already read, so parse whatever came in instead of giving up.
        data = BytesIO()
        for chunk in response.iter_content(chunk_size=8192):
            data.write(chunk)
            if data.tell() >= FAVICON_PAGE_MAX_BYTES:
                break
        base_url = response.url or page_url
        encoding = response.encoding or "utf-8"

    try:
        html = data.getvalue().decode(encoding, errors="replace")
    except LookupError:  # unknown charset declared by the server
        html = data.getvalue().decode("utf-8", errors="replace")
    parser = _IconLinkParser()
    parser.feed(html)

    urls = []
    for href in parser.icons + parser.touch_icons:
        absolute = urljoin(base_url, href)
        if urlparse(absolute).scheme in ALLOWED_SCHEMES and absolute not in urls:
            urls.append(absolute)
    return urls[:FAVICON_MAX_HTML_CANDIDATES]
