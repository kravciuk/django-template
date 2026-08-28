from django.urls import path

from . import views

app_name = "attachments"

urlpatterns = [
    path("<uuid:public_id>/download/", views.AttachmentDownloadView.as_view(), name="download"),
]
