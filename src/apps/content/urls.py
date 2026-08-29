from django.urls import path

from . import views

app_name = "content"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("add/", views.NoteFormView.as_view(), name="note_add"),
    path("add/autosave/", views.NoteAutosaveView.as_view(), name="note_autosave_add"),
    path("drafts/", views.DraftListView.as_view(), name="note_drafts"),
    path("tags/suggest/", views.tag_suggest, name="tag_suggest"),
    path("<uuid:public_id>/", views.NoteDetailView.as_view(), name="note_detail"),
    path("<uuid:public_id>/edit/", views.NoteFormView.as_view(), name="note_edit"),
    path("<uuid:public_id>/autosave/", views.NoteAutosaveView.as_view(), name="note_autosave_edit"),
]
