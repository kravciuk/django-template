"""Human-facing pages for apps.users (as opposed to urls.py's JWT API).

Kept separate from urls.py because this needs the i18n URL prefix that the
other human-facing apps get (see core/urls.py), while the JWT endpoints are
machine-consumed and stay unprefixed.
"""

from django.urls import path

from . import views

app_name = "users"

urlpatterns = [
    path("profile/", views.ProfileUpdateView.as_view(), name="profile"),
]
