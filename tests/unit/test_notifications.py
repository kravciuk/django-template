from unittest.mock import patch

import pytest
from django.urls import reverse

from apps.notifications.enums import NotificationKind
from apps.notifications.models import Notification
from apps.notifications.services import notify

pytestmark = pytest.mark.django_db


@pytest.fixture
def notification_factory(user):
    def make(*, recipient=None, **kwargs):
        recipient = recipient or user
        kwargs.setdefault("kind", NotificationKind.SYSTEM)
        kwargs.setdefault("payload", {"title": "Hello"})
        return Notification.objects.create(recipient=recipient, **kwargs)

    return make


def test_notify_creates_a_notification_and_pushes_it(user, django_capture_on_commit_callbacks):
    # notify() defers the push to transaction.on_commit(); pytest-django wraps
    # each test in a transaction that's rolled back, so on_commit callbacks
    # never fire on their own - django_capture_on_commit_callbacks(execute=True)
    # runs them anyway when the block exits.
    with patch("apps.notifications.services.push_notification") as mock_push, \
            django_capture_on_commit_callbacks(execute=True):
        notification = notify(user, kind=NotificationKind.SYSTEM, payload={"title": "Hi"})

    assert notification.recipient == user
    assert notification.sender is None
    assert notification.kind == NotificationKind.SYSTEM
    assert notification.payload == {"title": "Hi"}
    assert not notification.is_read
    mock_push.assert_called_once_with(notification)


def test_notify_records_an_optional_sender_and_target(user, other_user, notification_factory):
    target = notification_factory(recipient=other_user)

    with patch("apps.notifications.services.push_notification"):
        notification = notify(
            user, kind=NotificationKind.MESSAGE, payload={"body": "hi"}, sender=other_user, target=target,
        )

    assert notification.sender == other_user
    assert notification.target == target


def test_mark_read_sets_is_read_and_read_at_once(notification_factory):
    notification = notification_factory()
    assert not notification.is_read
    assert notification.read_at is None

    notification.mark_read()

    notification.refresh_from_db()
    assert notification.is_read
    assert notification.read_at is not None


def test_mark_read_is_a_noop_if_already_read(notification_factory):
    notification = notification_factory()
    notification.mark_read()
    first_read_at = notification.read_at

    notification.mark_read()

    notification.refresh_from_db()
    assert notification.read_at == first_read_at


def test_list_returns_only_the_logged_in_user_s_notifications(client, user, other_user, notification_factory):
    mine = notification_factory(payload={"title": "Mine"})
    notification_factory(recipient=other_user, payload={"title": "Not mine"})

    client.force_login(user)
    response = client.get(reverse("notifications:notification-list"))

    assert response.status_code == 200
    results = response.json()["results"]
    assert [item["id"] for item in results] == [mine.id]


def test_cannot_mark_another_user_s_notification_as_read(client, user, other_user, notification_factory):
    notification = notification_factory(recipient=other_user)
    client.force_login(user)

    response = client.post(reverse("notifications:notification-mark-read", args=[notification.id]))

    assert response.status_code == 404
    notification.refresh_from_db()
    assert not notification.is_read


def test_mark_read_endpoint_marks_own_notification(client, user, notification_factory):
    notification = notification_factory()
    client.force_login(user)

    response = client.post(reverse("notifications:notification-mark-read", args=[notification.id]))

    assert response.status_code == 204
    notification.refresh_from_db()
    assert notification.is_read


def test_mark_all_read_only_affects_own_unread_notifications(client, user, other_user, notification_factory):
    mine_unread = notification_factory()
    mine_read = notification_factory()
    mine_read.mark_read()
    others_unread = notification_factory(recipient=other_user)
    client.force_login(user)

    response = client.post(reverse("notifications:notification-mark-all-read"))

    assert response.status_code == 204
    mine_unread.refresh_from_db()
    others_unread.refresh_from_db()
    assert mine_unread.is_read
    assert not others_unread.is_read


def test_unread_count_counts_only_own_unread_notifications(client, user, other_user, notification_factory):
    notification_factory()
    read = notification_factory()
    read.mark_read()
    notification_factory(recipient=other_user)
    client.force_login(user)

    response = client.get(reverse("notifications:notification-unread-count"))

    assert response.status_code == 200
    assert response.json() == {"count": 1}


def test_admin_send_view_creates_and_pushes_a_message_notification(
    client, django_user_model, user, django_capture_on_commit_callbacks
):
    admin_user = django_user_model.objects.create_superuser("admin", "admin@example.com", "pw12345678")
    client.force_login(admin_user)

    with patch("apps.notifications.services.push_notification") as mock_push, \
            django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            reverse("admin:notifications_notification_send"),
            {"recipient": user.id, "title": "Hi", "body": "Hello there"},
        )

    assert response.status_code == 302
    notification = Notification.objects.get(recipient=user)
    assert notification.sender == admin_user
    assert notification.kind == NotificationKind.MESSAGE
    assert notification.payload == {"title": "Hi", "body": "Hello there"}
    mock_push.assert_called_once_with(notification)


def test_admin_send_view_requires_staff(client, user):
    client.force_login(user)

    response = client.get(reverse("admin:notifications_notification_send"))

    assert response.status_code == 302
    assert "/admin/login/" in response.url
