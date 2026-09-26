from pathlib import Path

from django.utils.translation import gettext_lazy as _

BASE_DIR = Path(__file__).resolve().parents[2]

LANGUAGE_CODE = "en"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

LANGUAGES = [
    ("en", _("English")),
    ("de", _("German")),
    ("fr", _("French")),
    ("es", _("Spanish")),
    ("it", _("Italian")),
    ("nl", _("Dutch")),
    ("ru", _("Russian")),
]

LOCALE_PATHS = [BASE_DIR / "locale"]
