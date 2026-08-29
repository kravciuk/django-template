from urllib.parse import urlparse

from django import template

register = template.Library()


@register.filter
def domain(url):
    """Renders just the host of a link's URL under its title, e.g.
    "https://chatgpt.com/foo?x=1" -> "chatgpt.com" - matches the compact
    card layout in .llm/links.md.
    """
    if not url:
        return ""
    return urlparse(url).netloc or url
