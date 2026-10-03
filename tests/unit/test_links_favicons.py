from io import BytesIO
from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from PIL import Image

from apps.links import services
from apps.links.models import Link, LinkGroup
from apps.links.tasks import refetch_missing_favicons


class FakeResponse:
    def __init__(self, url, status_code=200, content_type="", body=b""):
        self.url = url
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.encoding = "utf-8"
        self._body = body

    def iter_content(self, chunk_size):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def fake_get(responses):
    """Patch target for requests.get - answers from a {url: FakeResponse}
    map, 404 for anything else, and records every requested URL."""
    requested = []

    def get(url, **kwargs):
        requested.append(url)
        return responses.get(url) or FakeResponse(url, status_code=404, content_type="text/html")

    get.requested = requested
    return get


@pytest.fixture
def png_bytes():
    # Generated rather than conftest's tiny_png_bytes, which PIL's verify()
    # rejects (bad IDAT checksum) - fine where fetch_favicon is mocked, not here.
    buffer = BytesIO()
    Image.new("RGB", (1, 1)).save(buffer, format="PNG")
    return buffer.getvalue()


def png(url, body):
    return FakeResponse(url, content_type="image/png", body=body)


def test_favicon_ico_is_used_when_available(png_bytes):
    get = fake_get({"https://example.com/favicon.ico": png("https://example.com/favicon.ico", png_bytes)})

    with patch("apps.links.services.requests.get", get):
        favicon = services.fetch_favicon("https://example.com/some/page")

    assert favicon is not None
    assert favicon.name.endswith(".png")
    assert get.requested == ["https://example.com/favicon.ico"]


def test_falls_back_to_link_rel_icon_from_page_html(png_bytes):
    page = "https://example.com/app"
    html = b'<html><head><link rel="apple-touch-icon" href="/touch.png"><link rel="icon" href="/i.png"></head></html>'
    get = fake_get({
        page: FakeResponse(page, content_type="text/html; charset=utf-8", body=html),
        "https://example.com/i.png": png("https://example.com/i.png", png_bytes),
    })

    with patch("apps.links.services.requests.get", get):
        favicon = services.fetch_favicon(page)

    assert favicon is not None
    # rel="icon" is preferred over apple-touch-icon even when it comes later.
    assert get.requested == ["https://example.com/favicon.ico", page, "https://example.com/i.png"]


def test_falls_back_to_google_when_site_blocks_requests(png_bytes):
    google_url = services.GOOGLE_FAVICON_URL.format(host="example.com")
    get = fake_get({
        "https://example.com/favicon.ico": FakeResponse("", status_code=403, content_type="text/html"),
        "https://example.com/": FakeResponse("", status_code=403, content_type="text/html"),
        google_url: png(google_url, png_bytes),
    })

    with patch("apps.links.services.requests.get", get):
        favicon = services.fetch_favicon("https://example.com/")

    assert favicon is not None
    assert get.requested[-1] == google_url


def test_returns_none_when_every_source_fails():
    get = fake_get({})

    with patch("apps.links.services.requests.get", get):
        assert services.fetch_favicon("https://example.com/") is None


def test_html_page_not_served_as_an_image_is_rejected():
    get = fake_get({
        "https://example.com/favicon.ico": FakeResponse("", content_type="image/x-icon", body=b"<html>nope</html>"),
    })

    with patch("apps.links.services.requests.get", get):
        assert services.fetch_favicon("https://example.com/") is None


def test_corrupt_png_is_rejected_instead_of_raising(tiny_png_bytes):
    # tiny_png_bytes has a bad IDAT checksum - PIL raises SyntaxError for it.
    get = fake_get({"https://example.com/favicon.ico": png("https://example.com/favicon.ico", tiny_png_bytes)})

    with patch("apps.links.services.requests.get", get):
        assert services.fetch_favicon("https://example.com/") is None


@pytest.mark.parametrize("url",["ftp://example.com/file", "file:///etc/passwd", "not a url"])
def test_non_http_urls_are_never_requested(url):
    get = fake_get({})

    with patch("apps.links.services.requests.get", get):
        assert services.fetch_favicon(url) is None

    assert get.requested == []


@pytest.mark.django_db
def test_task_refetches_only_links_without_a_favicon(user, tiny_png_bytes):
    group = LinkGroup.objects.create(owner=user, title="Group")
    missing = Link.objects.create(group=group, url="https://missing.example", title="Missing", author=user)
    present = Link.objects.create(group=group, url="https://present.example", title="Present", author=user)
    present.favicon.save("old.png", ContentFile(tiny_png_bytes), save=True)
    old_name = present.favicon.name

    with patch("apps.links.services.fetch_favicon") as mock_fetch:
        mock_fetch.return_value = ContentFile(tiny_png_bytes, name="new.png")
        fixed = refetch_missing_favicons()

    assert fixed == 1
    mock_fetch.assert_called_once_with("https://missing.example")
    missing.refresh_from_db()
    present.refresh_from_db()
    assert missing.favicon
    assert present.favicon.name == old_name


@pytest.mark.django_db
def test_task_leaves_link_alone_when_fetch_still_fails(user):
    group = LinkGroup.objects.create(owner=user, title="Group")
    link = Link.objects.create(group=group, url="https://down.example", title="Down", author=user)

    with patch("apps.links.services.fetch_favicon", return_value=None):
        assert refetch_missing_favicons() == 0

    link.refresh_from_db()
    assert not link.favicon
