import logging

from django import template
from django.utils.html import format_html
from imagekit.cachefiles import ImageCacheFile
from imagekit.registry import generator_registry
from imagekit.templatetags.imagekit import DEFAULT_THUMBNAIL_GENERATOR

register = template.Library()
logger = logging.getLogger(__name__)


@register.simple_tag
def safe_thumbnail(source, width, height, css_class=""):
    """Same idea as imagekit's own {% thumbnail %} tag, but never raises.

    `Attachment.kind == "image"` is set from the file's mimetype/extension
    at upload time (see apps.attachments.models), not from Pillow actually
    being able to decode it - a corrupt upload, or a format Pillow can't
    read (e.g. HEIC without the pillow-heif plugin), would otherwise crash
    the whole page it's rendered on. One bad photo must never do that -
    callers render a fallback when this returns "".
    """
    if not source:
        return ""
    try:
        generator = generator_registry.get(DEFAULT_THUMBNAIL_GENERATOR, source=source, width=width, height=height)
        cache_file = ImageCacheFile(generator)
        cache_file.generate()  # force now, so a decode failure surfaces here, not on later <img> access
        return format_html(
            '<img src="{}" width="{}" height="{}" class="{}">',
            cache_file.url, cache_file.width, cache_file.height, css_class,
        )
    except Exception:
        logger.warning("Could not generate a thumbnail for %r", source, exc_info=True)
        return ""
