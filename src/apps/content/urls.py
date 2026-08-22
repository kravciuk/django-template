from django.urls import path

from . import views

app_name = "content"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("add/", views.NoteFormView.as_view(), name="note_add"),
    path("tags/suggest/", views.tag_suggest, name="tag_suggest"),
    path("<uuid:public_id>/", views.NoteDetailView.as_view(), name="note_detail"),
    path("<uuid:public_id>/edit/", views.NoteFormView.as_view(), name="note_edit"),
]
