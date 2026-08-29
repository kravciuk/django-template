from unittest.mock import patch

import pytest
from django.core.files.base import ContentFile
from django.urls import reverse

from apps.links.models import Link, LinkGroup

pytestmark = pytest.mark.django_db


@pytest.fixture
def group_factory(user):
    def make(*, owner=None, **kwargs):
        owner = owner or user
        kwargs.setdefault("title", "Group")
        kwargs.setdefault("cards_per_row", 4)
        return LinkGroup.objects.create(owner=owner, **kwargs)

    return make


def test_home_requires_login(client):
    response = client.get(reverse("links:home"))
    assert response.status_code == 302
    assert "/admin/login/" in response.url


def test_home_lists_only_the_logged_in_user_s_groups(client, user, other_user, group_factory):
    mine = group_factory(title="Mine")
    group_factory(title="Not mine", owner=other_user)

    client.force_login(user)
    response = client.get(reverse("links:home"))

    assert response.status_code == 200
    assert list(response.context["groups"]) == [mine]


def test_create_group_sets_owner_and_next_order(client, user, group_factory):
    group_factory()  # an existing group, default order=0
    client.force_login(user)

    response = client.post(reverse("links:group-list"), {"title": "New", "cards_per_row": 3})

    assert response.status_code == 201
    group = LinkGroup.objects.get(pk=response.json()["id"])
    assert group.owner == user
    assert group.order == 1


def test_rename_group_updates_title_and_cards_per_row(client, user, group_factory):
    group = group_factory(title="Old", cards_per_row=4)
    client.force_login(user)

    response = client.patch(
        reverse("links:group-detail", args=[group.id]),
        data={"title": "New", "cards_per_row": 2},
        content_type="application/json",
    )

    assert response.status_code == 200
    group.refresh_from_db()
    assert group.title == "New"
    assert group.cards_per_row == 2


def test_cannot_rename_or_delete_another_user_s_group(client, user, other_user, group_factory):
    group = group_factory(owner=other_user)
    client.force_login(user)

    response = client.patch(
        reverse("links:group-detail", args=[group.id]),
        data={"title": "Hijacked"},
        content_type="application/json",
    )
    assert response.status_code == 404

    response = client.delete(reverse("links:group-detail", args=[group.id]))
    assert response.status_code == 404


def test_delete_group_cascades_to_its_links(client, user, group_factory):
    group = group_factory()
    link = Link.objects.create(group=group, url="https://example.com", title="Example", author=user)
    client.force_login(user)

    response = client.delete(reverse("links:group-detail", args=[group.id]))

    assert response.status_code == 204
    assert not Link.objects.filter(pk=link.pk).exists()


def test_add_link_attaches_a_fetched_favicon(client, user, group_factory, tiny_png_bytes):
    group = group_factory()
    client.force_login(user)

    with patch("apps.links.api.fetch_favicon") as mock_fetch:
        mock_fetch.return_value = ContentFile(tiny_png_bytes, name="favicon.png")
        response = client.post(
            reverse("links:link-list"),
            {"title": "Example", "url": "https://example.com", "group": group.id},
        )

    assert response.status_code == 201
    link = Link.objects.get(pk=response.json()["id"])
    assert link.author == user
    assert link.favicon
    assert response.json()["favicon"]


def test_add_link_without_a_favicon_still_saves(client, user, group_factory):
    group = group_factory()
    client.force_login(user)

    with patch("apps.links.api.fetch_favicon", return_value=None):
        response = client.post(
            reverse("links:link-list"),
            {"title": "Example", "url": "https://example.com", "group": group.id},
        )

    assert response.status_code == 201
    link = Link.objects.get(pk=response.json()["id"])
    assert not link.favicon
    assert response.json()["favicon"] is None


def test_cannot_add_link_to_another_user_s_group(client, user, other_user, group_factory):
    group = group_factory(owner=other_user)
    client.force_login(user)

    response = client.post(
        reverse("links:link-list"),
        {"title": "Nope", "url": "https://example.com", "group": group.id},
    )

    assert response.status_code == 400


def test_delete_link(client, user, group_factory):
    group = group_factory()
    link = Link.objects.create(group=group, url="https://example.com", title="Example", author=user)
    client.force_login(user)

    response = client.delete(reverse("links:link-detail", args=[link.id]))

    assert response.status_code == 204
    assert not Link.objects.filter(pk=link.pk).exists()


def test_edit_link_updates_title_and_url(client, user, group_factory):
    group = group_factory()
    link = Link.objects.create(group=group, url="https://example.com", title="Old", author=user)
    client.force_login(user)

    with patch("apps.links.api.fetch_favicon", return_value=None) as mock_fetch:
        response = client.patch(
            reverse("links:link-detail", args=[link.id]),
            data={"title": "New", "url": "https://example.org"},
            content_type="application/json",
        )

    assert response.status_code == 200
    link.refresh_from_db()
    assert link.title == "New"
    assert link.url == "https://example.org"
    mock_fetch.assert_called_once_with("https://example.org")


def test_edit_link_without_url_change_does_not_refetch_favicon(client, user, group_factory):
    group = group_factory()
    link = Link.objects.create(group=group, url="https://example.com", title="Old", author=user)
    client.force_login(user)

    with patch("apps.links.api.fetch_favicon") as mock_fetch:
        response = client.patch(
            reverse("links:link-detail", args=[link.id]),
            data={"title": "New title only"},
            content_type="application/json",
        )

    assert response.status_code == 200
    link.refresh_from_db()
    assert link.title == "New title only"
    assert link.url == "https://example.com"
    mock_fetch.assert_not_called()


def test_edit_link_new_favicon_replaces_old_one(client, user, group_factory, tiny_png_bytes):
    group = group_factory()
    link = Link.objects.create(group=group, url="https://example.com", title="Old", author=user)
    client.force_login(user)

    with patch("apps.links.api.fetch_favicon") as mock_fetch:
        mock_fetch.return_value = ContentFile(tiny_png_bytes, name="new-favicon.png")
        response = client.patch(
            reverse("links:link-detail", args=[link.id]),
            data={"url": "https://example.org"},
            content_type="application/json",
        )

    assert response.status_code == 200
    link.refresh_from_db()
    assert link.favicon
    assert response.json()["favicon"]


def test_cannot_edit_another_user_s_link(client, user, other_user, group_factory):
    group = group_factory(owner=other_user)
    link = Link.objects.create(group=group, url="https://example.com", title="Old", author=other_user)
    client.force_login(user)

    response = client.patch(
        reverse("links:link-detail", args=[link.id]),
        data={"title": "Hijacked"},
        content_type="application/json",
    )

    assert response.status_code == 404
