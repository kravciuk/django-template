import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.attachments.enums import AttachmentKind
from apps.attachments.models import Attachment
from apps.common.enums import ContentFormat, Visibility
from apps.content.enums import NoteKind
from apps.content.forms import NoteForm
from apps.content.models import Note
from apps.content.text import excerpt

pytestmark = pytest.mark.django_db


def test_home_lists_only_alive_public_notes_newest_first(client, note_factory):
    public_old = note_factory(title="Old public", visibility=Visibility.PUBLIC)
    public_new = note_factory(title="New public", visibility=Visibility.PUBLIC)
    note_factory(title="Private", visibility=Visibility.PRIVATE)
    note_factory(title="Unlisted", visibility=Visibility.UNLISTED)
    trashed = note_factory(title="Trashed public", visibility=Visibility.PUBLIC)
    trashed.soft_delete()

    response = client.get(reverse("content:home"))

    titles = [entry["note"].title for entry in response.context["entries"]]
    assert titles == ["New public", "Old public"]
    assert public_new.title in response.content.decode()
    assert "Private" not in response.content.decode()


@pytest.mark.parametrize(
    "body_format,body,expected",
    [
        (ContentFormat.HTML, "<div>Hello <b>world</b>, this is a test</div><div>second</div>", "Hello world, this is a test"),
        (ContentFormat.HTML, "<p>one two three</p>", "one two three"),
        (ContentFormat.HTML, "plain inline text with no block tag at all here more", "plain inline text with no block tag at all here more"),
        (ContentFormat.PLAIN, "First paragraph here.\n\nSecond paragraph.", "First paragraph here."),
    ],
)
def test_excerpt_extraction(note_factory, body_format, body, expected):
    note = note_factory(title="N", body_format=body_format, body=body)
    assert excerpt(note) == expected


def test_excerpt_caps_at_twenty_words():
    class Fake:
        body_format = ContentFormat.HTML
        body = "<p>" + " ".join(f"word{i}" for i in range(30)) + "</p>"

    text = excerpt(Fake())
    assert text.endswith("…")
    assert len(text[:-1].split()) == 20


def test_detail_404s_for_non_owner_on_private_note(client, note_factory, other_user):
    note = note_factory(title="Secret", visibility=Visibility.PRIVATE)

    client.force_login(other_user)
    response = client.get(reverse("content:note_detail", args=[note.public_id]))

    assert response.status_code == 404


def test_detail_200s_for_owner_and_shows_edit_link(client, note_factory, user):
    note = note_factory(title="Mine", visibility=Visibility.PRIVATE, owner=user)

    client.force_login(user)
    response = client.get(reverse("content:note_detail", args=[note.public_id]))

    assert response.status_code == 200
    assert response.context["can_edit"] is True
    assert reverse("content:note_edit", args=[note.public_id]) in response.content.decode()


def test_detail_hides_edit_link_for_non_owner(client, note_factory, user, other_user):
    note = note_factory(title="Public one", visibility=Visibility.PUBLIC, owner=user)

    client.force_login(other_user)
    response = client.get(reverse("content:note_detail", args=[note.public_id]))

    assert response.status_code == 200
    assert response.context["can_edit"] is False
    assert reverse("content:note_edit", args=[note.public_id]) not in response.content.decode()


def test_add_note_requires_login(client):
    response = client.get(reverse("content:note_add"))
    assert response.status_code == 302
    assert "/admin/login/" in response.url


def test_add_note_creates_root_note(client, user):
    client.force_login(user)
    response = client.post(
        reverse("content:note_add"),
        {
            "title": "Root note",
            "kind": NoteKind.NOTE,
            "body_format": ContentFormat.PLAIN,
            "body": "hello",
            "visibility": Visibility.PUBLIC,
            "tags": "",
        },
    )

    note = Note.objects.get(title="Root note")
    assert response.status_code == 302
    assert note.owner_id == user.id
    assert note.depth == 1


def test_add_note_creates_child_note_with_parent(client, user, note_factory):
    parent = note_factory(title="Parent", owner=user)
    client.force_login(user)

    client.post(
        reverse("content:note_add"),
        {
            "title": "Child note",
            "kind": NoteKind.NOTE,
            "body_format": ContentFormat.PLAIN,
            "body": "hello",
            "visibility": Visibility.PRIVATE,
            "tags": "",
            "parent": parent.pk,
        },
    )

    child = Note.objects.get(title="Child note")
    assert Note.objects.get_parent(child).pk == parent.pk


def test_add_note_preselects_parent_from_query_param(client, user, note_factory):
    parent = note_factory(title="Parent", owner=user)

    client.force_login(user)
    response = client.get(reverse("content:note_add"), {"parent": str(parent.public_id)})

    assert response.context["form"].initial.get("parent") == parent


def test_add_note_ignores_parent_query_param_for_other_users_note(client, user, other_user, note_factory):
    other_note = note_factory(title="Not yours", owner=other_user)

    client.force_login(user)
    response = client.get(reverse("content:note_add"), {"parent": str(other_note.public_id)})

    assert response.status_code == 200
    assert "parent" not in response.context["form"].initial


def test_nav_add_link_carries_parent_on_own_note_detail_page(client, user, note_factory):
    note = note_factory(title="Mine", owner=user, visibility=Visibility.PUBLIC)

    client.force_login(user)
    response = client.get(reverse("content:note_detail", args=[note.public_id]))

    expected = f'{reverse("content:note_add")}?parent={note.public_id}'
    assert expected in response.content.decode()


def test_nav_add_link_plain_for_non_owner(client, user, other_user, note_factory):
    note = note_factory(title="Not yours", owner=other_user, visibility=Visibility.PUBLIC)

    client.force_login(user)
    response = client.get(reverse("content:note_detail", args=[note.public_id]))

    body = response.content.decode()
    assert f'href="{reverse("content:note_add")}"' in body
    assert f'?parent={note.public_id}' not in body


def test_edit_note_forbidden_for_non_owner(client, note_factory, other_user):
    note = note_factory(title="Mine")

    client.force_login(other_user)
    response = client.get(reverse("content:note_edit", args=[note.public_id]))

    assert response.status_code == 403


def test_edit_note_updates_fields_for_owner(client, note_factory, user):
    note = note_factory(title="Old title", owner=user, visibility=Visibility.PRIVATE)

    client.force_login(user)
    response = client.post(
        reverse("content:note_edit", args=[note.public_id]),
        {
            "title": "New title",
            "kind": NoteKind.NOTE,
            "body_format": ContentFormat.PLAIN,
            "body": "updated body",
            "visibility": Visibility.PUBLIC,
            "tags": "",
        },
    )

    note.refresh_from_db()
    assert response.status_code == 302
    assert note.title == "New title"
    assert note.visibility == Visibility.PUBLIC


def _base_note_fields(**overrides):
    fields = {
        "title": "With files",
        "kind": NoteKind.NOTE,
        "body_format": ContentFormat.PLAIN,
        "body": "hello",
        "visibility": Visibility.PUBLIC,
        "tags": "",
    }
    fields.update(overrides)
    return fields


def _valid_png_bytes():
    # tiny_png_bytes (conftest.py) is only header-valid - fine for the
    # metadata-population tests it was built for, but fails a real Pillow
    # decode/crop/resize, which imagekit's thumbnail generation needs.
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color=(200, 100, 50)).save(buf, format="PNG")
    return buf.getvalue()


def test_add_note_with_multiple_files_creates_an_attachment_per_file(client, user):
    client.force_login(user)
    files = [
        SimpleUploadedFile("a.txt", b"hello a", content_type="text/plain"),
        SimpleUploadedFile("b.txt", b"hello b", content_type="text/plain"),
    ]
    response = client.post(reverse("content:note_add"), {**_base_note_fields(), "attachments": files})

    note = Note.objects.get(title="With files")
    assert response.status_code == 302
    assert set(note.attachments.alive().values_list("original_name", flat=True)) == {"a.txt", "b.txt"}
    assert all(a.owner_id == user.id for a in note.attachments.alive())


def test_add_note_rejects_oversized_file(client, user, settings):
    settings.ATTACHMENTS_MAX_UPLOAD_SIZE = 10
    client.force_login(user)
    big_file = SimpleUploadedFile("big.txt", b"x" * 100, content_type="text/plain")

    response = client.post(reverse("content:note_add"), {**_base_note_fields(), "attachments": [big_file]})

    assert response.status_code == 200
    assert "attachments" in response.context["form"].errors
    assert not Note.objects.filter(title="With files").exists()


def test_add_note_rejects_too_many_files(client, user, settings):
    settings.ATTACHMENTS_MAX_FILES_PER_UPLOAD = 2
    client.force_login(user)
    files = [SimpleUploadedFile(f"f{i}.txt", b"x", content_type="text/plain") for i in range(3)]

    response = client.post(reverse("content:note_add"), {**_base_note_fields(), "attachments": files})

    assert response.status_code == 200
    assert "attachments" in response.context["form"].errors
    assert not Note.objects.filter(title="With files").exists()


def test_edit_note_removes_selected_attachments_only(client, user, note_factory):
    note = note_factory(title="Mine", owner=user)
    keep = note.attachments.create(owner=user, file=SimpleUploadedFile("keep.txt", b"1", content_type="text/plain"))
    remove = note.attachments.create(owner=user, file=SimpleUploadedFile("gone.txt", b"2", content_type="text/plain"))

    client.force_login(user)
    response = client.post(
        reverse("content:note_edit", args=[note.public_id]),
        {**_base_note_fields(title="Mine"), "remove_attachments": [remove.pk]},
    )

    assert response.status_code == 302
    keep.refresh_from_db()
    remove.refresh_from_db()
    assert keep.deleted_at is None
    assert remove.deleted_at is not None


def test_edit_note_cannot_remove_another_users_attachment(client, user, other_user, note_factory):
    note = note_factory(title="Mine", owner=user)
    other_note = note_factory(title="Not yours", owner=other_user)
    foreign = other_note.attachments.create(
        owner=other_user, file=SimpleUploadedFile("foreign.txt", b"1", content_type="text/plain"),
    )

    client.force_login(user)
    response = client.post(
        reverse("content:note_edit", args=[note.public_id]),
        {**_base_note_fields(title="Mine"), "remove_attachments": [foreign.pk]},
    )

    assert response.status_code == 200
    assert "remove_attachments" in response.context["form"].errors
    foreign.refresh_from_db()
    assert foreign.deleted_at is None


def test_detail_page_lists_alive_attachments_and_excludes_trashed(client, note_factory, user):
    note = note_factory(title="Mine", owner=user, visibility=Visibility.PUBLIC)
    alive = note.attachments.create(owner=user, file=SimpleUploadedFile("visible.txt", b"1", content_type="text/plain"))
    trashed = note.attachments.create(owner=user, file=SimpleUploadedFile("hidden.txt", b"2", content_type="text/plain"))
    trashed.soft_delete()

    response = client.get(reverse("content:note_detail", args=[note.public_id]))

    body = response.content.decode()
    assert "visible.txt" in body
    assert "hidden.txt" not in body
    assert Attachment.objects.filter(pk=alive.pk, deleted_at__isnull=True).exists()


def test_note_form_kind_field_only_offers_note_and_album(user):
    form = NoteForm(owner=user)
    values = [choice[0] for choice in form.fields["kind"].choices]
    assert set(values) == {NoteKind.NOTE, NoteKind.ALBUM}


def test_note_form_has_no_cover_picker(user, note_factory):
    # Cover selection duplicated the remove-files checkbox list (same
    # filenames in two places) and was removed - lock that in.
    note = note_factory(title="Mine", owner=user)
    assert "cover_attachment" not in NoteForm(owner=user).fields
    assert "cover_attachment" not in NoteForm(instance=note, owner=user).fields


def test_add_note_with_kind_album_persists(client, user):
    client.force_login(user)
    response = client.post(
        reverse("content:note_add"),
        _base_note_fields(title="An album", kind=NoteKind.ALBUM),
    )

    note = Note.objects.get(title="An album")
    assert response.status_code == 302
    assert note.kind == NoteKind.ALBUM


def test_detail_page_renders_thumbnail_for_image_and_link_for_other_file(client, note_factory, user):
    note = note_factory(title="Mixed", owner=user, visibility=Visibility.PUBLIC)
    note.attachments.create(owner=user, file=SimpleUploadedFile("photo.png", _valid_png_bytes(), content_type="image/png"))
    note.attachments.create(owner=user, file=SimpleUploadedFile("doc.txt", b"hi", content_type="text/plain"))

    response = client.get(reverse("content:note_detail", args=[note.public_id]))

    assert response.status_code == 200
    assert list(response.context["images"])[0].kind == AttachmentKind.IMAGE
    assert list(response.context["other_files"])[0].original_name == "doc.txt"
    body = response.content.decode()
    assert "note-gallery" in body
    assert "doc.txt" in body


def test_home_entry_includes_cover_for_note_with_image(client, note_factory, user):
    note = note_factory(title="Album note", owner=user, visibility=Visibility.PUBLIC)
    cover = note.attachments.create(
        owner=user, file=SimpleUploadedFile("cover.png", _valid_png_bytes(), content_type="image/png"), is_cover=True,
    )

    response = client.get(reverse("content:home"))

    entries = {e["note"].pk: e for e in response.context["entries"]}
    assert entries[note.pk]["cover"].pk == cover.pk
