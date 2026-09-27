from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

# Named "users_api", not "users" - apps.users.page_urls (the human-facing
# profile page) already owns the "users" namespace, and reusing the same
# app_name for both includes trips Django's urls.W005 "namespace isn't
# unique" system check even though the individual url names don't collide.
app_name = "users_api"

urlpatterns = [
    # JWT: SIMPLE_JWT was configured in settings but never wired to an
    # endpoint - added here so a non-browser client (see
    # apps.notifications.ws_auth) has a way to actually obtain a token.
    # Note: this bypasses allauth's rate limiting/2FA entirely (it accepts
    # username+password directly) - see docs/security-considerations.md.
    path("token/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
]
