import os

CORS_ALLOWED_ORIGINS = [
    o.strip() for o in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",") if o.strip()
]
CORS_ALLOW_CREDENTIALS = True

TAGGIT_CASE_INSENSITIVE = True

# Always re-encode generated thumbnails as JPEG regardless of the source
# format - without this, imagekit preserves the source format, and a HEIC
# photo (the default on iPhones) would produce a HEIC "thumbnail" that only
# Safari can actually display in an <img> tag.
IMAGEKIT_DEFAULT_THUMBNAIL_FORMAT = "JPEG"

# CKEditor5 is wired in as a form widget only (apps/content/admin.py) - Note.body
# stays a plain TextField, so the schema never depends on this package.
CKEDITOR_5_CONFIGS = {
    "default": {
        "toolbar": ["heading", "|", "bold", "italic", "link", "bulletedList", "numberedList", "blockQuote"],
        # Without a licenseKey, CKEditor5 renders a "Powered by CKEditor" badge
        # in the editor's corner on every page load (client-side, baked into
        # the vendored bundle.js - a container/static restart never clears it).
        # "GPL" is CKEditor5's own self-hosted open-source license key and
        # suppresses the badge for GPL-licensed use.
        "licenseKey": "GPL",
    },
    "content_note": {
        "toolbar": [
            "heading", "|",
            "bold", "italic", "underline", "strikethrough", "subscript", "superscript", "|",
            "link", "bulletedList", "numberedList", "blockQuote", "insertTable", "codeBlock", "|",
            "undo", "redo", "sourceEditing",
        ],
        "table": {
            "contentToolbar": ["tableColumn", "tableRow", "mergeTableCells"],
        },
        "licenseKey": "GPL",
    },
}
