"""Short "list view" excerpts for Note.body.

Rule (confirmed with the user): take the text of the first block-level tag
(<div> or <p>) for HTML bodies, or the first paragraph (up to the first blank
line) for markdown/plain bodies - either way capped to 20 words.
"""

import re
from html.parser import HTMLParser

from django.utils.html import strip_tags

from apps.common.enums import ContentFormat

DEFAULT_MAX_WORDS = 20
_WORD_RE = re.compile(r"\S+")
_BLOCK_TAGS = {"div", "p"}


class _FirstBlockExtractor(HTMLParser):
    """Collects the text content of the first top-level <div> or <p>,
    tracking nesting depth so a same-tag child doesn't end extraction early.
    """

    def __init__(self):
        super().__init__()
        self._found_tag = None
        self._depth = 0
        self._chunks = []
        self.done = False

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        if self._found_tag is None:
            if tag in _BLOCK_TAGS:
                self._found_tag = tag
                self._depth = 1
            return
        if tag == self._found_tag:
            self._depth += 1

    def handle_endtag(self, tag):
        if self.done or self._found_tag is None or tag != self._found_tag:
            return
        self._depth -= 1
        if self._depth == 0:
            self.done = True

    def handle_data(self, data):
        if self._found_tag is not None and not self.done:
            self._chunks.append(data)

    @property
    def text(self):
        return "".join(self._chunks)


def _cap_words(text, max_words):
    words = _WORD_RE.findall(text)
    if not words:
        return ""
    if len(words) > max_words:
        return " ".join(words[:max_words]) + "…"
    return " ".join(words)


def excerpt(note, max_words=DEFAULT_MAX_WORDS):
    """Short preview text for `note`, per the rule above."""
    body = note.body or ""
    if note.body_format == ContentFormat.HTML:
        parser = _FirstBlockExtractor()
        parser.feed(body)
        text = parser.text.strip()
        if not text:
            text = strip_tags(body)
    else:
        text = body.strip().split("\n\n", 1)[0]
    return _cap_words(text, max_words)
