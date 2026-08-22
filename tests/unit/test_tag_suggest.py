import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_tag_suggest_requires_login(client):
    response = client.get(reverse("content:tag_suggest"), {"q": "py"})
    assert response.status_code == 302
    assert "/admin/login/" in response.url


def test_tag_suggest_returns_matching_tags_case_insensitively(client, user, note_factory):
    note_factory(title="Note A").tags.add("Python", "python-tips", "Django")

    client.force_login(user)
    response = client.get(reverse("content:tag_suggest"), {"q": "PYTH"})

    assert response.status_code == 200
    # Order isn't asserted - it depends on the DB's collation for mixed-case
    # sorting, which this test shouldn't need to know about.
    assert set(response.json()["results"]) == {"Python", "python-tips"}


def test_tag_suggest_blank_query_returns_empty_without_matching_everything(client, user, note_factory):
    note_factory(title="Note A").tags.add("anything")

    client.force_login(user)
    response = client.get(reverse("content:tag_suggest"), {"q": ""})

    assert response.json() == {"results": []}


def test_tag_suggest_caps_results(client, user, note_factory):
    note = note_factory(title="Note A")
    note.tags.add(*[f"tag{i}" for i in range(15)])

    client.force_login(user)
    response = client.get(reverse("content:tag_suggest"), {"q": "tag"})

    assert len(response.json()["results"]) == 10
