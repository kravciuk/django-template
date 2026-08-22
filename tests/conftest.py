import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(username="alice", password="password123")


@pytest.fixture
def other_user(db):
    User = get_user_model()
    return User.objects.create_user(username="bob", password="password123")


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
