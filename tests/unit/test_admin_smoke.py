import pytest

pytestmark = pytest.mark.django_db


def test_admin_pages_render(client, django_user_model):
    """Exercises the wiring unit tests don't reach: TreeAdmin, the
    CKEditor5 widget swap in NoteForm, and the generic inlines
    (attachments/comments/sharing) actually rendering without a template
    or import error.
    """
    admin_user = django_user_model.objects.create_superuser("smoketest", "smoke@example.com", "pw12345678")
    client.force_login(admin_user)

    urls = [
        "/admin/",
        "/admin/content/note/",
        "/admin/content/note/add/",
        "/admin/attachments/attachment/",
        "/admin/attachments/attachment/add/",
        "/admin/comments/comment/",
        "/admin/sharing/sharelink/",
        "/admin/sharing/sharelink/add/",
        "/admin/notifications/notification/",
        "/admin/notifications/notification/send/",
    ]
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200, (url, response.status_code, response.content[:2000])
