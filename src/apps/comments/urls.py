from django.urls import path

from . import views

app_name = "comments"

urlpatterns = [
    path("<slug:target_kind>/<uuid:public_id>/", views.CommentThreadView.as_view(), name="thread"),
    path("<slug:target_kind>/<uuid:public_id>/new/", views.CommentCreateView.as_view(), name="create"),
    path("<int:pk>/reply/", views.CommentReplyView.as_view(), name="reply"),
    path("<int:pk>/edit/", views.CommentEditView.as_view(), name="edit"),
    path("<int:pk>/delete/", views.CommentDeleteView.as_view(), name="delete"),
]
