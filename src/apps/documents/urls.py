from django.urls import path

from . import views

app_name = "documents"

urlpatterns = [
    path("", views.DocumentListView.as_view(), name="list"),
    path("add/", views.DocumentFormView.as_view(), name="add"),
    path("<uuid:public_id>/", views.DocumentDetailView.as_view(), name="detail"),
    path("<uuid:public_id>/edit/", views.DocumentFormView.as_view(), name="edit"),
    path("<uuid:public_id>/delete/", views.DocumentDeleteView.as_view(), name="delete"),
]
