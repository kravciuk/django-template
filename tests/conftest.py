import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(username="alice", email="alice@example.com", password="password123")


@pytest.fixture
def other_user(db):
    User = get_user_model()
    return User.objects.create_user(username="bob", email="bob@example.com", password="password123")


@pytest.fixture
def note_factory(db, user):
    from apps.content.models import Note

    def make(*, parent=None, owner=None, **kwargs):
        owner = owner or user
        kwargs.setdefault("title", "Untitled")
        if parent is None:
            return Note.objects.add_root(instance=Note(owner=owner, **kwargs))
        return Note.objects.add_child(parent, instance=Note(owner=owner, **kwargs))

    return make


@pytest.fixture
def tiny_png_bytes():
    # A valid 1x1 transparent PNG, small enough to embed inline.
    return bytes.fromhex(
        "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415478da6360000002000155009c1a75220000000049454e44"
        "ae426082"
    )


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    # Never write test uploads into the real bind-mounted var/media/.
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture(autouse=True)
def _cache_locmem(settings, request):
    # core/settings/auth.py points CACHES at the real Redis instance so
    # allauth's ACCOUNT_RATE_LIMITS has a shared backend in dev/prod - tests
    # share that same Redis (see CELERY_BROKER_URL/REDIS_URL elsewhere), so
    # without this override, rate-limit counters would persist and compound
    # across test runs instead of resetting per test. A unique LOCATION per
    # test is required too - LocMemCache keeps its backing dict in a
    # process-wide registry keyed by LOCATION, so every test sharing the
    # default empty LOCATION would still see each other's counters.
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": request.node.nodeid,
        }
    }
