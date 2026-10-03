import html
import re

import nh3
from django.utils.html import strip_tags

# `table`/`pre`/`code`/`span[class]` are kept deliberately: the spec calls
# for storing chord sheets and sheet-music markup, which rely on this markup
# for layout. `script`, `style`, `iframe`, event-handler attributes (on*) and
# javascript: URLs are never in the allowlist, so nh3 strips them regardless.
ALLOWED_TAGS = {
    "p", "br", "hr", "div", "span",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "b", "em", "i", "u", "s", "sub", "sup",
    "ul", "ol", "li",
    "a", "img",
    "blockquote", "pre", "code",
    "table", "thead", "tbody", "tr", "th", "td",
}

ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "target", "rel"},
    "img": {"src", "alt", "title", "width", "height"},
    "span": {"class"},
    "code": {"class"},
    "th": {"colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
}


def sanitize_html(value):
    """Strip anything outside the allowlist above before HTML is persisted.

    Called from apps.content.models.Note.save() whenever body_format is
    HTML, so it applies no matter which entry point (admin, future API)
    wrote the note.
    """
    if not value:
        return value
    # link_rel=None: nh3 manages the "rel" attribute on <a> itself by default
    # (injecting "noopener noreferrer"), which conflicts with "rel" also
    # being in ALLOWED_ATTRIBUTES and raises ValueError. Disabling nh3's own
    # rel management lets our allowlist take effect instead.
    return nh3.clean(value, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, link_rel=None)


_BLOCK_BREAK_RE = re.compile(r"<\s*br\s*/?>|</\s*(p|div|li|h[1-6]|tr|blockquote|pre)\s*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[a-zA-Z/!][^>]*>")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def looks_like_html(value):
    return bool(value) and bool(_TAG_RE.search(value))


def html_to_text(value):
    """Readable plain text from an HTML fragment: line breaks for <br> and
    block ends, tags dropped, entities decoded. Used where only plain text
    is accepted (e.g. Google Calendar event descriptions)."""
    if not value:
        return ""
    text = _BLOCK_BREAK_RE.sub("\n", value)
    text = html.unescape(strip_tags(text))
    text = "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))
    return _BLANK_LINES_RE.sub("\n\n", text).strip()
