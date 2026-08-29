import markdown
from django import template
from django.utils.safestring import mark_safe

from libs.html import sanitize_html

register = template.Library()

# fenced_code: ```lang blocks, rendered as <pre><code class="language-...">
# (allowed - libs.html.ALLOWED_TAGS keeps pre/code, and code's class
# attribute is explicitly allowlisted for exactly this).
# nl2br: a bare newline becomes <br> - closer to how a short comment box
# behaves, without forcing every reply into markdown's normal
# blank-line-separated-paragraph convention.
MARKDOWN_EXTENSIONS = ["fenced_code", "nl2br"]


@register.filter
def render_comment_body(value):
    """Comment.body always stores the raw Markdown source exactly as
    typed (no model change - Comment.save()'s edited_at stamping, via
    _original_body, diffs on that raw text). Rendering to HTML happens
    here, at display time only, then through the SAME sanitize_html()
    allowlist apps.content.Note's HTML body already uses - a comment
    can't inject anything a note body couldn't either. mark_safe() means
    the template uses this directly, no `|safe` needed.
    """
    if not value:
        return ""
    html = markdown.markdown(value, extensions=MARKDOWN_EXTENSIONS)
    return mark_safe(sanitize_html(html))
